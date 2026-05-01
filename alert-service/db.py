"""Singleton Motor (async MongoDB) client for the alert service.

The Motor client is created lazily on first access. The ASGI lifespan in
``app.py`` calls :func:`ensure_indexes` once at startup so the index DDL runs
on a fresh deployment.
"""

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

import settings


logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None


def db() -> AsyncIOMotorDatabase:
    global _client
    client = _client
    if client is None:
        client = AsyncIOMotorClient(settings.MONGO_URI, tz_aware=True)
        _client = client
    return client[settings.MONGO_ALERTS_DB_NAME]


async def ensure_indexes() -> None:
    """Create the indexes the alert pipeline depends on. Idempotent."""
    alerts = db()["alerts"]
    await alerts.create_index([("productId", 1), ("enabled", 1)], name="productId_enabled")
    await alerts.create_index([("userId", 1)], name="userId")
    logger.info("alert-service indexes ensured")


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
