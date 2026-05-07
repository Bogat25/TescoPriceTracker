"""Keycloak JWT validation for incoming Bearer tokens (via Gateway proxy).

Fetches the realm JWKS through the gateway's internal proxy endpoint and caches
it in-memory with a TTL. On a verification failure that *might* be due to key
rotation, the cache is invalidated and a single retry is performed. The decoded
`sub` and `email` claims are exposed to route handlers via the `current_user`
dependency.

All Keycloak communication goes through Gateway.API's /internal/keycloak/*
endpoints, authenticated by X-Internal-Token header.
"""

import logging
import time
from typing import Optional

import httpx
import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKSet, PyJWTError

import settings


logger = logging.getLogger(__name__)


class _JwksCache:
    """Fetches JWKS via httpx with X-Internal-Token, caches with TTL.

    Uses httpx.get directly (instead of PyJWKClient/urllib) so the
    X-Internal-Token header is sent as-is without urllib's capitalize()
    normalisation, and so that JWKS fetch failures produce actionable log
    lines that include the HTTP status code and whether the token was present.
    """

    def __init__(self, jwks_url: str, ttl: int) -> None:
        self._url = jwks_url
        self._ttl = ttl
        self._jwk_set: Optional[PyJWKSet] = None
        self._loaded_at: float = 0.0

    def _fetch(self) -> PyJWKSet:
        headers: dict = {}
        if settings.GATEWAY_INTERNAL_TOKEN:
            headers["X-Internal-Token"] = settings.GATEWAY_INTERNAL_TOKEN
        else:
            logger.warning(
                "GATEWAY_INTERNAL_TOKEN is not set — JWKS request to %s carries no auth "
                "header and will be rejected (HTTP 403) by the gateway.",
                self._url,
            )

        logger.info("fetching JWKS from %s", self._url)
        try:
            r = httpx.get(self._url, headers=headers, timeout=30.0)
        except Exception as exc:
            logger.error(
                "JWKS network error fetching %s: %s: %s", self._url, type(exc).__name__, exc
            )
            raise PyJWTError(f"JWKS network error: {exc}") from exc

        if r.status_code != 200:
            logger.error(
                "JWKS fetch failed: HTTP %d from %s — "
                "X-Internal-Token was %s. "
                "Ensure GATEWAY_INTERNAL_TOKEN (alert-service) matches "
                "INTERNAL_SERVICE_TOKEN (gateway).",
                r.status_code,
                self._url,
                "SENT" if settings.GATEWAY_INTERNAL_TOKEN else "NOT SENT (GATEWAY_INTERNAL_TOKEN is empty)",
            )
            raise PyJWTError(f"JWKS endpoint returned HTTP {r.status_code}")

        try:
            return PyJWKSet.from_dict(r.json())
        except Exception as exc:
            logger.error("Failed to parse JWKS response from %s: %s", self._url, exc)
            raise PyJWTError(f"JWKS parse error: {exc}") from exc

    def _jwk_set_or_load(self) -> PyJWKSet:
        if self._jwk_set is None or (time.time() - self._loaded_at) > self._ttl:
            self._jwk_set = self._fetch()
            self._loaded_at = time.time()
        return self._jwk_set

    def get_signing_key(self, token: str):
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise PyJWTError(f"Cannot decode token header: {exc}") from exc

        kid = header.get("kid")
        jwk_set = self._jwk_set_or_load()

        for jwk in jwk_set.keys:
            if kid is None or jwk.key_id == kid:
                return jwk.key

        # No kid match — warn and fall back to first key (single-key realms)
        if jwk_set.keys:
            logger.warning("No JWK matched kid=%r; falling back to first available key", kid)
            return jwk_set.keys[0].key

        raise PyJWTError(f"JWKS contained no usable keys (kid={kid!r})")

    def invalidate(self) -> None:
        self._jwk_set = None
        self._loaded_at = 0.0


# JWKS URL now points to Gateway's internal proxy endpoint
_jwks_url = f"{settings.KC_INTERNAL_BASE_URL}/certs"
_jwks = _JwksCache(_jwks_url, settings.JWKS_TTL_SECONDS)


def prime_jwks() -> None:
    """Fetch and cache JWKS at startup to verify connectivity and warm the cache."""
    try:
        _jwks.invalidate()
        _jwks._jwk_set_or_load()
        n = len(_jwks._jwk_set.keys) if _jwks._jwk_set else 0
        logger.info("JWKS primed: %d key(s) cached from %s", n, _jwks_url)
    except Exception:
        logger.exception(
            "JWKS prime FAILED — alerts will return 401 on every request until resolved. "
            "Most likely cause: GATEWAY_INTERNAL_TOKEN env var is empty or "
            "INTERNAL_SERVICE_TOKEN is not configured on the gateway."
        )


def _decode(token: str) -> dict:
    key = _jwks.get_signing_key(token)
    return jwt.decode(
        token,
        key=key,
        algorithms=["RS256", "RS384", "RS512"],
        issuer=settings.KC_ISSUER,
        options={"verify_aud": False, "require": ["exp", "iat", "sub", "iss"]},
    )


def _safe_dump_claims(token: str) -> str:
    """Best-effort decode without verification to log what's actually in the
    token when validation fails. Values are truncated to 80 chars and tokens
    that fail to parse return a placeholder. Never raises."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        # Show short scalar claims in full; truncate longer ones; list keys for dicts/arrays.
        safe = {}
        for k, v in unverified.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                s = str(v)
                safe[k] = s if len(s) <= 80 else f"{s[:77]}..."
            else:
                safe[k] = f"<{type(v).__name__} keys={list(v.keys()) if isinstance(v, dict) else len(v)}>"
        return repr(safe)
    except Exception as e:
        return f"<unparseable: {type(e).__name__}: {e}>"


def _validate_bearer(token: str) -> dict:
    try:
        claims = _decode(token)
    except PyJWTError as first_err:
        # Could be key rotation — drop cache and retry once.
        _jwks.invalidate()
        try:
            claims = _decode(token)
        except PyJWTError as e:
            # Log at WARNING with type+message so 401s are diagnosable in prod.
            # Most common causes: ExpiredSignatureError, InvalidIssuerError
            # (KC_ISSUER mismatch), InvalidSignatureError (wrong realm/JWKS),
            # MissingRequiredClaimError (Keycloak client/scope not emitting it).
            logger.warning(
                "JWT validation failed: %s: %s (first attempt: %s: %s); expected iss=%s; token claims=%s",
                type(e).__name__, e,
                type(first_err).__name__, first_err,
                settings.KC_ISSUER,
                _safe_dump_claims(token),
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    azp = claims.get("azp")
    if azp and azp != settings.KC_CLIENT_ID:
        logger.warning(
            "JWT azp mismatch: token azp=%r, expected KC_CLIENT_ID=%r",
            azp, settings.KC_CLIENT_ID,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token audience")

    if not claims.get("sub"):
        logger.warning("JWT missing sub claim; claims keys=%s", list(claims.keys()))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing sub claim")

    return claims


async def _userinfo_email(token: str) -> Optional[str]:
    """Fallback: fetch email from Keycloak userinfo endpoint via Gateway proxy."""
    url = f"{settings.KC_INTERNAL_BASE_URL}/userinfo"
    headers = {"X-Downstream-Token": token}
    if settings.GATEWAY_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = settings.GATEWAY_INTERNAL_TOKEN
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return r.json().get("email")
    except httpx.HTTPError:
        logger.exception("userinfo fetch via gateway failed")
    return None


async def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency: validate Bearer JWT, return {sub, email}.

    Performs a JIT upsert into the local users cache so batch processing later can
    map userIds to emails without contacting Keycloak.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    claims = _validate_bearer(token)

    sub = claims["sub"]
    email = claims.get("email")
    if not email:
        email = await _userinfo_email(token)

    # Lazy import avoids a circular dependency: services.user_repo imports the Mongo
    # client, which is initialized in app.py during the lifespan.
    from services import user_repo

    if email:
        await user_repo.upsert(sub, email)

    return {"sub": sub, "email": email}
