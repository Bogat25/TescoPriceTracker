"""Alert-service FastAPI entrypoint."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db as alert_db
import settings
from auth import prime_jwks
from routers import alerts, health, internal


logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("alert-service")


def _enforce_gateway_only() -> None:
    """Startup check: refuse to boot if Keycloak URLs point directly to Keycloak
    instead of going through the gateway. This enforces the architectural rule
    that all external communication must be mediated by Gateway.API."""
    blocked_patterns = ["keycloak:8080", "keycloak:9000", "localhost:8080/realms"]

    violations = []
    for name, value in [
        ("KC_INTERNAL_BASE_URL", settings.KC_INTERNAL_BASE_URL),
        ("KC_ADMIN_BASE_URL", settings.KC_ADMIN_BASE_URL),
    ]:
        for pattern in blocked_patterns:
            if pattern in value:
                violations.append(f"  {name}={value} (contains '{pattern}' — direct Keycloak access)")

    if violations:
        msg = (
            "\n\n"
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  GATEWAY ENFORCEMENT VIOLATION                             ║\n"
            "║  All Keycloak communication MUST go through Gateway.API.   ║\n"
            "║  The following env vars point directly to Keycloak:        ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
            + "\n".join(violations) + "\n\n"
            "Fix: Set KC_INTERNAL_BASE_URL and KC_ADMIN_BASE_URL to point to\n"
            "the gateway's internal proxy (e.g. http://gavaller-backend-gateway:8080/internal/keycloak)\n"
        )
        logger.critical(msg)
        raise RuntimeError(
            "Gateway enforcement failed: services must communicate through Gateway.API, "
            "not directly to Keycloak. Check KC_INTERNAL_BASE_URL and KC_ADMIN_BASE_URL."
        )

    if not settings.GATEWAY_INTERNAL_TOKEN:
        logger.warning(
            "GATEWAY_INTERNAL_TOKEN is empty — internal proxy calls will be rejected by the gateway."
        )

    logger.info("Gateway enforcement check passed: all Keycloak URLs route through gateway")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _enforce_gateway_only()
    await alert_db.ensure_indexes()
    prime_jwks()
    try:
        yield
    finally:
        await alert_db.close()


app = FastAPI(
    title="alert-service",
    version="1.0.0",
    lifespan=lifespan,
    # FastAPI's default trailing-slash redirect builds an absolute URL from the
    # Host header. Behind nginx that header is the upstream service name, so the
    # 307 leaks an unreachable internal URL to the browser (mixed-content). We
    # accept both forms explicitly on the routes instead.
    redirect_slashes=False,
)


_cors_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health.router)
app.include_router(alerts.router)
app.include_router(internal.router)
