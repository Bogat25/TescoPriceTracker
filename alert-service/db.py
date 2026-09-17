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


async def migrate_legacy_alerts(alerts=None) -> int:
    """Give alerts saved before multi-store support a target and stores. Idempotent.

    Those alerts watch one Tesco product by its bare tpnc (``productId``), which
    stays unchanged because the browser extension still matches on it.
    """
    alerts = alerts if alerts is not None else db()["alerts"]
    result = await alerts.update_many(
        {"target": {"$exists": False}},
        [{"$set": {"target": {"$concat": ["tesco:", {"$toString": "$productId"}]}, "stores": ["tesco"]}}],
    )
    if result.modified_count:
        logger.info(
            "Gave %d existing alerts a Tesco target.", result.modified_count,
            extra={"Action": "alerts.migrated", "Category": "job"},
        )
    return result.modified_count


async def ensure_indexes() -> None:
    """Create the indexes the alert pipeline depends on, migrating old alerts first. Idempotent."""
    alerts = db()["alerts"]
    await migrate_legacy_alerts(alerts)
    await alerts.create_index([("productId", 1), ("enabled", 1)], name="productId_enabled")
    await alerts.create_index([("target", 1), ("enabled", 1)], name="target_enabled")
    await alerts.create_index([("userId", 1)], name="userId")
    logger.info("alert-service indexes ensured")


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
