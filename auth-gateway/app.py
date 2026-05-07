"""
Auth gateway: handles the OIDC dance with Keycloak so the SPA only deals with
cookies. Owned by /auth/* routes on the same origin as the frontend.

Contract (do not break — other services depend on it):
  GET /auth/login?returnUrl=...           -> 302 to Keycloak authorize
  GET /auth/callback?code&state           -> exchanges code, sets session cookie, 302 to returnUrl
  GET /auth/userinfo                      -> {Name, Claims[]} or 401
  GET /auth/token                         -> {access_token, expires_in} for Bearer-only backends, or 401
  GET /auth/logout?returnUrl=...          -> clears cookie, 302 to Keycloak end-session
  GET /auth/extension-relay               -> after login: creates one-time ext_code, 302 to /auth/extension-done?ext_code=...
  GET /auth/extension-done?ext_code=...   -> landing page the browser extension monitors for
  GET /auth/extension-token?code=...      -> returns {access_token,refresh_token,...} for ext_code, then invalidates it
  GET /auth/account               -> 302 to Keycloak account management (requires session)
  GET /auth/health                -> {ok: true}
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from typing import Optional, Tuple
from urllib.parse import urlencode, urlparse, quote

import httpx
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
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
# To support key rotation, multiple comma-separated keys can be passed in SESSION_SECRET.
# MultiFernet uses the first key for encryption, and attempts decryption with all keys.
_fernets = [
    Fernet(base64.urlsafe_b64encode(hashlib.sha256(sec.strip().encode()).digest()))
    for sec in _required("SESSION_SECRET").split(",") if sec.strip()
]
_fernet = MultiFernet(_fernets)

AUTH_ENDPOINT_PUBLIC = f"{KC_PUBLIC_BASE_URL}/protocol/openid-connect/auth"
LOGOUT_ENDPOINT_PUBLIC = f"{KC_PUBLIC_BASE_URL}/protocol/openid-connect/logout"
ACCOUNT_ENDPOINT_PUBLIC = f"{KC_PUBLIC_BASE_URL}/account"
TOKEN_ENDPOINT_INTERNAL = f"{KC_INTERNAL_BASE_URL}/protocol/openid-connect/token"
USERINFO_ENDPOINT_INTERNAL = f"{KC_INTERNAL_BASE_URL}/protocol/openid-connect/userinfo"

# ── One-time extension auth codes ────────────────────────────────────────────
# Maps ext_code -> {tokens, exp}. Short-lived (90 s TTL). Single-process only.
_EXT_CODES: dict = {}
_EXT_CODE_TTL = 90  # seconds


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
    # Allow root-relative paths (/auth/extension-relay etc.)
    # Guard against protocol-relative URLs (//evil.com) by requiring no netloc.
    if not p.scheme and not p.netloc:
        return url if url.startswith("/") else default
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
    if not data:
        return None
    # Allow expired sessions through — the caller will attempt token refresh.
    return data


def _is_session_expired(session: dict) -> bool:
    return session.get("exp", 0) < int(time.time())


app = FastAPI(title="auth-gateway", version="1.0.0")

# ── CORS for browser-extension endpoints ─────────────────────────────────────
# Extension service workers have chrome-extension:// / moz-extension:// origins
# which cannot match the same-origin policy of the site. The extension token and
# refresh endpoints are one-time-code exchanges only (no session cookies), so it
# is safe to allow any origin on those specific routes.
_EXT_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}

def _ext_cors(response):
    """Attach extension-endpoint CORS headers to a response object in-place."""
    for k, v in _EXT_CORS_HEADERS.items():
        response.headers[k] = v
    return response


@app.get("/auth/health")
async def health():
    return {"ok": True}


@app.get("/auth/login")
async def login(returnUrl: Optional[str] = None, prompt: Optional[str] = None):
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
    # Only "login" is accepted as a prompt value (whitelist); prevents open-redirect abuse.
    if prompt == "login":
        params["prompt"] = "login"
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
    # Use refresh token expiry for cookie lifetime so the browser keeps the cookie
    # long enough for the gateway to attempt a token refresh.
    refresh_expires_in = int(tokens.get("refresh_expires_in", 1800))

    # Extract name/email from the id_token payload (JWT middle segment, base64url).
    # We trust this token because we just fetched it directly from Keycloak.
    name: Optional[str] = None
    email: Optional[str] = None
    id_tok = tokens.get("id_token") or tokens.get("access_token")
    if id_tok:
        try:
            import base64 as _b64
            parts = id_tok.split(".")
            if len(parts) >= 2:
                pad = 4 - len(parts[1]) % 4
                raw_claims = json.loads(_b64.urlsafe_b64decode(parts[1] + "=" * pad))
                name  = raw_claims.get("preferred_username") or raw_claims.get("name") or raw_claims.get("email")
                email = raw_claims.get("email")
        except Exception:
            pass  # Best effort — extension relay will fallback gracefully

    session = {
        "at":    tokens["access_token"],
        "rt":    tokens.get("refresh_token"),
        "it":    tokens.get("id_token"),
        "exp":   int(time.time()) + expires_in,
        "name":  name,
        "email": email,
    }

    resp = RedirectResponse(state_data["r"], status_code=302)
    _set_session_cookie(resp, _seal(session), max_age=refresh_expires_in)
    return resp


async def _refresh_tokens(session: dict) -> Optional[dict]:
    """Use the refresh token to obtain a new access token from Keycloak."""
    rt = session.get("rt")
    if not rt:
        return None
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": KC_CLIENT_ID,
    }
    if KC_CLIENT_SECRET:
        payload["client_secret"] = KC_CLIENT_SECRET
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                TOKEN_ENDPOINT_INTERNAL,
                data=payload,
                headers={"Accept": "application/json"},
            )
        if r.status_code != 200:
            logger.debug("token refresh failed: %s", r.status_code)
            return None
        tokens = r.json()
        expires_in = int(tokens.get("expires_in", 300))
        return {
            "at":    tokens["access_token"],
            "rt":    tokens.get("refresh_token", rt),
            "it":    tokens.get("id_token", session.get("it")),
            "exp":   int(time.time()) + expires_in,
            # Carry forward name/email — they don't change on refresh.
            "name":  session.get("name"),
            "email": session.get("email"),
        }
    except Exception:
        logger.exception("token refresh error")
        return None


@app.get("/auth/userinfo")
async def userinfo(request: Request):
    from fastapi.responses import JSONResponse

    session = _read_session(request)
    if not session:
        raise HTTPException(401, "not authenticated")

    refreshed_session = None

    # If the access token has expired, try refreshing before calling userinfo.
    if _is_session_expired(session):
        refreshed_session = await _refresh_tokens(session)
        if not refreshed_session:
            raise HTTPException(401, "session expired and refresh failed")
        session = refreshed_session

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            USERINFO_ENDPOINT_INTERNAL,
            headers={"Authorization": f"Bearer {session['at']}"},
        )

    # If userinfo rejected (e.g. token revoked), attempt one refresh.
    if r.status_code != 200 and not refreshed_session:
        refreshed_session = await _refresh_tokens(session)
        if not refreshed_session:
            raise HTTPException(401, "userinfo rejected")
        session = refreshed_session
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                USERINFO_ENDPOINT_INTERNAL,
                headers={"Authorization": f"Bearer {session['at']}"},
            )
        if r.status_code != 200:
            raise HTTPException(401, "userinfo rejected after refresh")

    info = r.json()
    name = info.get("preferred_username") or info.get("name") or info.get("email") or "user"
    claims = [{"Type": k, "Value": str(v)} for k, v in info.items() if v is not None]

    # If we refreshed, update the session cookie in the response.
    if refreshed_session:
        expires_in = refreshed_session["exp"] - int(time.time())
        resp = JSONResponse({"Name": name, "Claims": claims})
        _set_session_cookie(resp, _seal(refreshed_session), max_age=max(expires_in, 60))
        return resp

    return {"Name": name, "Claims": claims}


@app.get("/auth/token")
async def token(request: Request):
    """Return the current access token so the SPA can attach it as Bearer
    to backend services that validate JWTs directly (e.g. alert-service).
    Auto-refreshes if the access token has expired.
    """
    from fastapi.responses import JSONResponse

    session = _read_session(request)
    if not session:
        raise HTTPException(401, "not authenticated")

    refreshed = None
    if _is_session_expired(session):
        refreshed = await _refresh_tokens(session)
        if not refreshed:
            raise HTTPException(401, "session expired and refresh failed")
        session = refreshed

    expires_in = max(int(session["exp"] - time.time()), 0)
    body = {"access_token": session["at"], "expires_in": expires_in}
    if refreshed:
        resp = JSONResponse(body)
        # Persist the refreshed tokens back into the session cookie.
        _set_session_cookie(resp, _seal(refreshed), max_age=max(expires_in, 60))
        return resp
    return body


@app.get("/auth/account")
async def account(request: Request):
    session = _read_session(request)
    if not session:
        return RedirectResponse(f"/auth/login?returnUrl=/auth/account", status_code=302)
    return RedirectResponse(ACCOUNT_ENDPOINT_PUBLIC, status_code=302)


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


@app.get("/auth/switch-account")
async def switch_account(request: Request, returnUrl: Optional[str] = None):
    """
    Sign out the current user and redirect to /auth/login with prompt=login so
    Keycloak is forced to show the credential form even if a session is still alive.
    This lets users log in as a different account without silently re-using the
    existing Keycloak session.
    """
    validated_return = _safe_return_url(returnUrl, POST_LOGOUT_REDIRECT_DEFAULT)
    # After Keycloak logs the user out, land on login with prompt=login and the
    # original returnUrl so the user ends up back where they started.
    post_logout_login = f"/auth/login?returnUrl={quote(validated_return, safe='')}&prompt=login"
    session = _read_session(request)

    params = {
        "client_id": KC_CLIENT_ID,
        "post_logout_redirect_uri": _safe_return_url(post_logout_login, POST_LOGOUT_REDIRECT_DEFAULT),
    }
    if session and session.get("it"):
        params["id_token_hint"] = session["it"]

    resp = RedirectResponse(f"{LOGOUT_ENDPOINT_PUBLIC}?{urlencode(params)}", status_code=302)
    _clear_session_cookie(resp)
    return resp


# ── Browser extension auth endpoints ─────────────────────────────────────────

@app.get("/auth/extension-relay")
async def extension_relay(request: Request):
    """
    After the normal auth flow completes and the auth-gateway redirects here,
    create a short-lived one-time ext_code and redirect to /auth/extension-done.
    The extension monitors the tab for that URL, extracts the code, then
    calls /auth/extension-token to exchange it for real tokens.
    """
    session = _read_session(request)
    if not session:
        # Not logged in — redirect to login, using an absolute returnUrl so
        # _safe_return_url accepts it (scheme required for absolute URLs).
        # We reconstruct the absolute URL from the request's host header.
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        scheme = request.headers.get("x-forwarded-proto", "https")
        relay_url = f"{scheme}://{host}/auth/extension-relay"
        return RedirectResponse(
            f"/auth/login?returnUrl={relay_url}",
            status_code=302,
        )

    # Purge stale codes
    now = int(time.time())
    stale = [k for k, v in _EXT_CODES.items() if v["exp"] < now]
    for k in stale:
        _EXT_CODES.pop(k, None)

    ext_code = str(uuid.uuid4())
    _EXT_CODES[ext_code] = {
        "at": session["at"],
        "rt": session.get("rt"),
        "it": session.get("it"),
        "exp": now + _EXT_CODE_TTL,
        # Include user identity so extension-token can return it inline
        # (avoids a separate userinfo round-trip from the extension)
        "name": session.get("name"),
        "email": session.get("email"),
    }

    return RedirectResponse(
        f"/auth/extension-done?ext_code={ext_code}",
        status_code=302,
    )


@app.get("/auth/extension-done")
async def extension_done(ext_code: Optional[str] = None):
    """
    Landing page that the extension's tabs.onUpdated listener watches for.
    The extension closes this tab immediately after catching the URL.
    Returns a minimal HTML page so the user sees a friendly message
    if the tab is briefly visible.
    """
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Signed in</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f5f7fa;}
.card{text-align:center;padding:40px;border-radius:12px;background:#fff;box-shadow:0 4px 20px rgba(0,0,0,.08);}
h2{color:#00539f;margin-bottom:8px;}p{color:#6b7280;}</style></head>
<body><div class="card"><h2>&#10003; Signed in successfully</h2>
<p>You can close this tab. The extension has been authenticated.</p></div></body></html>"""
    return HTMLResponse(html)


@app.get("/auth/extension-token")
async def extension_token(code: Optional[str] = None):
    """
    Exchange a one-time ext_code for the actual tokens.
    The code is invalidated immediately after use.
    CORS: allows any origin so extension service workers can call this.
    """
    from fastapi.responses import JSONResponse

    if not code:
        raise HTTPException(400, "missing code")

    entry = _EXT_CODES.pop(code, None)
    if not entry:
        raise HTTPException(404, "code not found or already used")

    now = int(time.time())
    if entry["exp"] < now:
        raise HTTPException(410, "code expired")

    expires_in = max(entry["exp"] - now, 0)
    return _ext_cors(JSONResponse({
        "access_token":  entry["at"],
        "refresh_token": entry.get("rt"),
        "id_token":      entry.get("it"),
        "expires_in":    expires_in,
        "name":          entry.get("name"),
        "email":         entry.get("email"),
    }))


@app.options("/auth/extension-token")
async def extension_token_preflight():
    from fastapi.responses import Response
    return _ext_cors(Response(status_code=204))


@app.post("/auth/extension-refresh")
async def extension_refresh(request: Request):
    """
    Refresh an extension's access token using a stored refresh token.
    Expects JSON body: {"refresh_token": "..."}
    Returns: {"access_token", "refresh_token", "expires_in"}
    Proxies to Keycloak internally — the extension never needs the Keycloak URL.
    CORS: allows any origin so extension service workers can call this.
    """
    from fastapi.responses import JSONResponse

    body = await request.json()
    refresh_tok = body.get("refresh_token") if body else None
    if not refresh_tok:
        raise HTTPException(400, "missing refresh_token")

    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_tok,
        "client_id":     KC_CLIENT_ID,
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
        logger.warning("extension token refresh failed: %s %s", r.status_code, r.text)
        raise HTTPException(401, "refresh failed")

    tokens = r.json()
    return _ext_cors(JSONResponse({
        "access_token":  tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_in":    tokens.get("expires_in", 300),
    }))


@app.options("/auth/extension-refresh")
async def extension_refresh_preflight():
    from fastapi.responses import Response
    return _ext_cors(Response(status_code=204))


@app.get("/auth/extension-userinfo")
async def extension_userinfo(request: Request):
    """
    Proxy a userinfo request to Keycloak using the extension's Bearer token.
    The extension sends Authorization: Bearer <access_token>.
    Returns Keycloak's userinfo payload.
    """
    from fastapi.responses import JSONResponse

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing or invalid Authorization header")

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            USERINFO_ENDPOINT_INTERNAL,
            headers={"Authorization": auth_header, "Accept": "application/json"},
        )
    if r.status_code != 200:
        raise HTTPException(r.status_code, "userinfo request failed")
    return JSONResponse(r.json())
