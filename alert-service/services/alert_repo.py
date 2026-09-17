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


def _prefs_coll():
    return db()["user_prefs"]


def _to_out(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "userId": doc["userId"],
        "productId": doc["productId"],
        # Alerts saved before targets existed are Tesco offer alerts.
        "target": doc.get("target") or f"tesco:{doc['productId']}",
        "stores": doc.get("stores") or ["tesco"],
        "alertType": doc["alertType"],
        "targetPrice": doc.get("targetPrice"),
        "dropPercentage": doc.get("dropPercentage"),
        "basePriceAtCreation": doc.get("basePriceAtCreation"),
        "enabled": doc.get("enabled", True),
        "createdAt": doc.get("createdAt"),
    }


async def create(user_id: str, payload: dict) -> dict:
    """``payload`` carries the normalised ``target``, ``productId`` and ``stores``."""
    doc = {
        "userId": user_id,
        "productId": payload["productId"],
        "target": payload["target"],
        "stores": list(payload["stores"]),
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


async def get_email_preference(user_id: str) -> bool:
    """Return the user's emailEnabled preference (default: True)."""
    doc = await _prefs_coll().find_one({"userId": user_id}, {"emailEnabled": 1})
    if doc is None:
        return True
    return doc.get("emailEnabled", True)


async def set_email_preference(user_id: str, email_enabled: bool) -> bool:
    """Upsert the user's emailEnabled preference. Returns the stored value."""
    await _prefs_coll().update_one(
        {"userId": user_id},
        {"$set": {"emailEnabled": email_enabled}},
        upsert=True,
    )
    return email_enabled


async def find_active_for_products(targets: list[str]) -> list[dict]:
    """Enabled alerts watching any of ``targets`` (offer references or groups).

    Fans out the ``{target: $in chunk}`` queries in parallel.
    """
    if not targets:
        return []
    unique_ids = list({target for target in targets if target})
    chunks = list(_chunks(unique_ids, settings.TRIGGER_CHUNK_SIZE))

    async def _query(chunk: list[str]) -> list[dict]:
        cursor = _coll().find(
            {"target": {"$in": chunk}, "enabled": True},
        )
        return [d async for d in cursor]

    results = await asyncio.gather(*(_query(c) for c in chunks))
    flat: list[dict] = []
    for r in results:
        flat.extend(r)
    return flat


def _trigger_runs_coll():
    return db()["trigger_runs"]


async def is_trigger_run_completed(run_key: str) -> bool:
    """True when a trigger with this key already finished sending its digests."""
    doc = await _trigger_runs_coll().find_one(
        {"_id": run_key, "status": "completed"}, {"_id": 1}
    )
    return doc is not None


async def mark_trigger_run_completed(run_key: str, summary: dict) -> None:
    await _trigger_runs_coll().update_one(
        {"_id": run_key},
        {"$set": {**summary, "status": "completed", "completedAt": datetime.now(timezone.utc)}},
        upsert=True,
    )
