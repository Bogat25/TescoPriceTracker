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


@asynccontextmanager
async def lifespan(_: FastAPI):
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
