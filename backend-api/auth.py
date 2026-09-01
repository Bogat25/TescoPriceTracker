"""Bearer-token validation for endpoints that use a caller's identity."""

import logging
import os
from functools import lru_cache
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _jwk_client() -> jwt.PyJWKClient:
    url = os.environ.get(
        "KC_JWKS_URL",
        "http://gavaller-backend-gateway:8080/internal/keycloak/be/certs",
    )
    token = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
    headers = {"X-Internal-Token": token} if token else None
    return jwt.PyJWKClient(url, headers=headers, cache_jwk_set=True, lifespan=3600)


def _validate_bearer(token: str) -> dict:
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=os.environ.get(
                "KC_ISSUER",
                "https://auth.gavaller.com/realms/backend-ecosystem",
            ).rstrip("/"),
            options={
                "verify_aud": False,
                "require": ["exp", "iat", "iss", "sub", "azp"],
            },
        )
    except (jwt.PyJWTError, OSError) as exc:
        logger.warning("Recommendation JWT validation failed: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc

    expected_client = os.environ.get("KC_CLIENT_ID", "gateway-client")
    if claims.get("azp") != expected_client:
        logger.warning("Recommendation JWT rejected due to authorized-party mismatch")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token audience")
    return claims


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid authorization header")
    return token.strip()


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    token = _token_from_header(authorization)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return _validate_bearer(token)


def optional_current_user(
    authorization: Optional[str] = Header(default=None),
) -> Optional[dict]:
    token = _token_from_header(authorization)
    return _validate_bearer(token) if token is not None else None
