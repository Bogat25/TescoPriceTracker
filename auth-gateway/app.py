"""
Auth gateway: handles the OIDC dance with Keycloak so the SPA only deals with
cookies. Owned by /auth/* routes on the same origin as the frontend.

Contract (do not break — other services depend on it):
  GET /auth/login?returnUrl=...   -> 302 to Keycloak authorize
  GET /auth/callback?code&state   -> exchanges code, sets session cookie, 302 to returnUrl
  GET /auth/userinfo              -> {Name, Claims[]} or 401
  GET /auth/logout?returnUrl=...  -> clears cookie, 302 to Keycloak end-session
  GET /auth/health                -> {ok: true}
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("auth-gateway")


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"missing required env var: {name}")
    return v


KC_PUBLIC_BASE_URL = _required("KC_PUBLIC_BASE_URL").rstrip("/")
KC_INTERNAL_BASE_URL = os.environ.get("KC_INTERNAL_BASE_URL", KC_PUBLIC_BASE_URL).rstrip("/")
KC_CLIENT_ID = _required("KC_CLIENT_ID")
KC_CLIENT_SECRET = os.environ.get("KC_CLIENT_SECRET", "")

GATEWAY_REDIRECT_URI = _required("GATEWAY_REDIRECT_URI")
POST_LOGIN_REDIRECT_DEFAULT = _required("POST_LOGIN_REDIRECT_DEFAULT")
POST_LOGOUT_REDIRECT_DEFAULT = _required("POST_LOGOUT_REDIRECT_DEFAULT")

RETURN_URL_ALLOWED_HOSTS = {
    h.strip() for h in os.environ.get("RETURN_URL_ALLOWED_HOSTS", "").split(",") if h.strip()
}

SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "tesco_auth")
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
SCOPES = os.environ.get("SCOPES", "openid profile email")

# Fernet needs a 32-byte url-safe base64 key; SHA-256 of any user-supplied secret works.
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_required("SESSION_SECRET").encode()).digest()))

AUTH_ENDPOINT_PUBLIC = f"{KC_PUBLIC_BASE_URL}/protocol/openid-connect/auth"
LOGOUT_ENDPOINT_PUBLIC = f"{KC_PUBLIC_BASE_URL}/protocol/openid-connect/logout"
TOKEN_ENDPOINT_INTERNAL = f"{KC_INTERNAL_BASE_URL}/protocol/openid-connect/token"
USERINFO_ENDPOINT_INTERNAL = f"{KC_INTERNAL_BASE_URL}/protocol/openid-connect/userinfo"


def _b64url_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _make_pkce() -> Tuple[str, str]:
    verifier = _b64url_no_pad(secrets.token_bytes(32))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _seal(payload: dict) -> str:
    return _fernet.encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _unseal(token: str, max_age: Optional[int] = None) -> Optional[dict]:
    try:
        raw = _fernet.decrypt(token.encode(), ttl=max_age)
        return json.loads(raw)
    except (InvalidToken, ValueError):
        return None


def _safe_return_url(url: Optional[str], default: str) -> str:
    if not url:
        return default
    try:
        p = urlparse(url)
    except ValueError:
        return default
    if p.scheme not in ("http", "https"):
        return default
    if RETURN_URL_ALLOWED_HOSTS and p.hostname not in RETURN_URL_ALLOWED_HOSTS:
        return default
    return url


def _set_session_cookie(resp, value: str, max_age: int) -> None:
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        domain=COOKIE_DOMAIN,
        path="/",
    )


def _clear_session_cookie(resp) -> None:
    resp.delete_cookie(key=SESSION_COOKIE_NAME, domain=COOKIE_DOMAIN, path="/")


def _read_session(request: Request) -> Optional[dict]:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    data = _unseal(raw)
    if not data or data.get("exp", 0) < int(time.time()):
        return None
    return data


app = FastAPI(title="auth-gateway", version="1.0.0")


@app.get("/auth/health")
async def health():
    return {"ok": True}


@app.get("/auth/login")
async def login(returnUrl: Optional[str] = None):
    verifier, challenge = _make_pkce()
    return_to = _safe_return_url(returnUrl, POST_LOGIN_REDIRECT_DEFAULT)
    state = _seal({"v": verifier, "r": return_to, "t": int(time.time())})

    params = {
        "client_id": KC_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": GATEWAY_REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return RedirectResponse(f"{AUTH_ENDPOINT_PUBLIC}?{urlencode(params)}", status_code=302)


@app.get("/auth/callback")
async def callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        raise HTTPException(400, detail={"error": error, "description": error_description})
    if not code or not state:
        raise HTTPException(400, "missing code or state")

    state_data = _unseal(state, max_age=600)
    if not state_data:
        raise HTTPException(400, "invalid or expired state")

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": GATEWAY_REDIRECT_URI,
        "client_id": KC_CLIENT_ID,
        "code_verifier": state_data["v"],
    }
    if KC_CLIENT_SECRET:
        payload["client_secret"] = KC_CLIENT_SECRET

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            TOKEN_ENDPOINT_INTERNAL,
            data=payload,
            headers={"Accept": "application/json"},
        )
    if r.status_code != 200:
        logger.warning("token exchange failed: %s %s", r.status_code, r.text)
        raise HTTPException(400, "token exchange failed")

    tokens = r.json()
    expires_in = int(tokens.get("expires_in", 300))
    session = {
        "at": tokens["access_token"],
        "rt": tokens.get("refresh_token"),
        "it": tokens.get("id_token"),
        "exp": int(time.time()) + expires_in,
    }

    resp = RedirectResponse(state_data["r"], status_code=302)
    _set_session_cookie(resp, _seal(session), max_age=expires_in)
    return resp


@app.get("/auth/userinfo")
async def userinfo(request: Request):
    session = _read_session(request)
    if not session:
        raise HTTPException(401, "not authenticated")

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            USERINFO_ENDPOINT_INTERNAL,
            headers={"Authorization": f"Bearer {session['at']}"},
        )
    if r.status_code != 200:
        raise HTTPException(401, "userinfo rejected")
    info = r.json()

    name = info.get("preferred_username") or info.get("name") or info.get("email") or "user"
    claims = [{"Type": k, "Value": str(v)} for k, v in info.items() if v is not None]
    return {"Name": name, "Claims": claims}


@app.get("/auth/logout")
async def logout(request: Request, returnUrl: Optional[str] = None):
    return_to = _safe_return_url(returnUrl, POST_LOGOUT_REDIRECT_DEFAULT)
    session = _read_session(request)

    params = {
        "client_id": KC_CLIENT_ID,
        "post_logout_redirect_uri": return_to,
    }
    if session and session.get("it"):
        params["id_token_hint"] = session["it"]

    resp = RedirectResponse(f"{LOGOUT_ENDPOINT_PUBLIC}?{urlencode(params)}", status_code=302)
    _clear_session_cookie(resp)
    return resp
