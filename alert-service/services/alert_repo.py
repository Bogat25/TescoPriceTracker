"""CRUD for the ``alerts`` collection."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from bson import ObjectId
from bson.errors import InvalidId

from db import db
import settings


logger = logging.getLogger(__name__)


def _coll():
    return db()["alerts"]


def _to_out(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "userId": doc["userId"],
        "productId": doc["productId"],
        "alertType": doc["alertType"],
        "targetPrice": doc.get("targetPrice"),
        "dropPercentage": doc.get("dropPercentage"),
        "basePriceAtCreation": doc.get("basePriceAtCreation"),
        "enabled": doc.get("enabled", True),
        "createdAt": doc.get("createdAt"),
    }


async def create(user_id: str, payload: dict) -> dict:
    doc = {
        "userId": user_id,
        "productId": payload["productId"],
        "alertType": payload["alertType"],
        "enabled": True,
        "createdAt": datetime.now(timezone.utc),
    }
    if payload["alertType"] == "TARGET_PRICE":
        doc["targetPrice"] = float(payload["targetPrice"])
    else:
        doc["dropPercentage"] = float(payload["dropPercentage"])
        doc["basePriceAtCreation"] = float(payload["basePriceAtCreation"])

    result = await _coll().insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_out(doc)


async def list_for_user(user_id: str) -> list[dict]:
    cursor = _coll().find({"userId": user_id}).sort("createdAt", -1)
    return [_to_out(d) async for d in cursor]


async def delete(user_id: str, alert_id: str) -> bool:
    try:
        oid = ObjectId(alert_id)
    except (InvalidId, TypeError):
        return False
    result = await _coll().delete_one({"_id": oid, "userId": user_id})
    return result.deleted_count == 1


async def toggle(user_id: str, alert_id: str, enabled: bool) -> dict | None:
    """Set the enabled flag on a specific alert. Returns the updated doc or None."""
    try:
        oid = ObjectId(alert_id)
    except (InvalidId, TypeError):
        return None
    result = await _coll().find_one_and_update(
        {"_id": oid, "userId": user_id},
        {"$set": {"enabled": enabled}},
        return_document=True,
    )
    if result is None:
        return None
    return _to_out(result)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def find_active_for_products(product_ids: list[str]) -> list[dict]:
    """Fan out the {productId: $in chunks} queries in parallel."""
    if not product_ids:
        return []
    unique_ids = list({pid for pid in product_ids if pid})
    chunks = list(_chunks(unique_ids, settings.TRIGGER_CHUNK_SIZE))

    async def _query(chunk: list[str]) -> list[dict]:
        cursor = _coll().find(
            {"productId": {"$in": chunk}, "enabled": True},
        )
        return [d async for d in cursor]

    results = await asyncio.gather(*(_query(c) for c in chunks))
    flat: list[dict] = []
    for r in results:
        flat.extend(r)
    return flat
