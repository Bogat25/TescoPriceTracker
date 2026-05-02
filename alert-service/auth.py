"""Keycloak JWT validation for incoming Bearer tokens.

Fetches the realm JWKS once and caches it in-memory with a TTL. On a verification
failure that *might* be due to key rotation, the cache is invalidated and a single
retry is performed. The decoded `sub` and `email` claims are exposed to route
handlers via the `current_user` dependency.
"""

import logging
import time
from typing import Optional

import httpx
import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient, PyJWTError

import settings


logger = logging.getLogger(__name__)


class _JwksCache:
    """Thin wrapper around PyJWKClient with manual TTL invalidation."""

    def __init__(self, jwks_url: str, ttl: int) -> None:
        self._url = jwks_url
        self._ttl = ttl
        self._client: Optional[PyJWKClient] = None
        self._loaded_at: float = 0.0

    def _client_or_load(self) -> PyJWKClient:
        if self._client is None or (time.time() - self._loaded_at) > self._ttl:
            logger.info("loading JWKS from %s", self._url)
            self._client = PyJWKClient(self._url, cache_keys=True, lifespan=self._ttl)
            self._loaded_at = time.time()
        return self._client

    def get_signing_key(self, token: str):
        return self._client_or_load().get_signing_key_from_jwt(token).key

    def invalidate(self) -> None:
        self._client = None
        self._loaded_at = 0.0


_jwks_url = f"{settings.KC_INTERNAL_BASE_URL}/protocol/openid-connect/certs"
_jwks = _JwksCache(_jwks_url, settings.JWKS_TTL_SECONDS)


def prime_jwks() -> None:
    """Force-load the JWKS during app startup so the first request is fast."""
    try:
        _jwks._client_or_load()
        logger.info("JWKS primed")
    except Exception:
        logger.exception("JWKS prime failed; will retry on first request")


def _decode(token: str) -> dict:
    key = _jwks.get_signing_key(token)
    return jwt.decode(
        token,
        key=key,
        algorithms=["RS256", "RS384", "RS512"],
        issuer=settings.KC_ISSUER,
        options={"verify_aud": False, "require": ["exp", "iat", "sub", "iss"]},
    )


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
            # (KC_ISSUER mismatch), InvalidSignatureError (wrong realm/JWKS).
            logger.warning(
                "JWT validation failed: %s: %s (first attempt: %s: %s); expected iss=%s",
                type(e).__name__, e,
                type(first_err).__name__, first_err,
                settings.KC_ISSUER,
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
    """Fallback: fetch email from Keycloak userinfo endpoint when not in the token."""
    url = f"{settings.KC_INTERNAL_BASE_URL}/protocol/openid-connect/userinfo"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            return r.json().get("email")
    except httpx.HTTPError:
        logger.exception("userinfo fetch failed")
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
