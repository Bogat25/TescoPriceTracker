"""Local cache of Keycloak users → email, used for batch alert delivery.

The cache is populated two ways: a JIT upsert on every authenticated request
(see ``auth.current_user``) and a daily Keycloak Admin API sweep
(``jobs/keycloak_sync.py``) that picks up users who haven't logged in.
"""

from datetime import datetime, timezone
from typing import Iterable

from db import db


def _coll():
    return db()["users"]


async def upsert(sub: str, email: str) -> None:
    await _coll().update_one(
        {"_id": sub},
        {"$set": {"email": email, "lastSyncedAt": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def emails_for(user_ids: Iterable[str]) -> dict[str, str]:
    ids = list({uid for uid in user_ids if uid})
    if not ids:
        return {}
    cursor = _coll().find({"_id": {"$in": ids}}, {"_id": 1, "email": 1})
    out: dict[str, str] = {}
    async for doc in cursor:
        email = doc.get("email")
        if email:
            out[doc["_id"]] = email
    return out
