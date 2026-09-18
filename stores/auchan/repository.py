"""MongoDB storage for Auchan products and crawl runs.

``auchan_products`` holds one document per Auchan product with a daily
``price_history``; ``auchan_runs`` holds one crawl state per day.
"""

import logging
from datetime import datetime
from typing import Optional

from pymongo import ASCENDING, DESCENDING, TEXT, UpdateOne
from pymongo import errors as mongo_errors

from mongo import database_manager as db
from stores import offers


logger = logging.getLogger(__name__)

PRODUCTS_COLLECTION = "auchan_products"
RUNS_COLLECTION = "auchan_runs"

# A new name (or a first sighting) means the embedding text and the product
# description may be stale.
_TEXT_FIELDS = ("name", "brand", "category_path")


class RepositoryError(RuntimeError):
    pass


def products():
    return db.get_database()[PRODUCTS_COLLECTION]


def runs():
    return db.get_database()[RUNS_COLLECTION]


def ensure_indexes() -> None:
    coll = products()
    coll.create_index([("name", TEXT), ("brand", TEXT)], name="auchan_text", default_language="none")
    coll.create_index("gtin_norm", sparse=True)
    coll.create_index("last_seen")
    coll.create_index("needs_details", sparse=True)
    coll.create_index("category_path")
    for name, fields in (
        ("browse_price_asc", [("browse_sort.has_price", DESCENDING), ("browse_sort.effective_price", ASCENDING), ("name", ASCENDING)]),
        ("browse_price_desc", [("browse_sort.has_price", DESCENDING), ("browse_sort.effective_price", DESCENDING), ("name", ASCENDING)]),
        ("browse_discount_asc", [("browse_sort.has_discount", DESCENDING), ("browse_sort.discount_ratio", ASCENDING), ("name", ASCENDING)]),
        ("browse_discount_desc", [("browse_sort.has_discount", DESCENDING), ("browse_sort.discount_ratio", DESCENDING), ("name", ASCENDING)]),
    ):
        coll.create_index(fields, name=name)


def browse_sort_fields(price_set: dict) -> dict:
    effective = offers.effective_price(price_set)
    ratio = offers.discount_ratio(price_set)
    return {
        "version": 1,
        "has_price": effective is not None,
        "effective_price": effective,
        "has_discount": ratio > 0,
        "discount_ratio": ratio,
    }


def _merge_history(history, today: str, row: dict) -> list:
    """Replace today's entry (a later pass is a fresher snapshot) or append it."""
    history = [entry for entry in (history or []) if isinstance(entry, dict)]
    for index, entry in enumerate(history):
        if entry.get("date") == today:
            history[index] = row
            return history
    history.append(row)
    return sorted(history, key=lambda entry: entry.get("date") or "")


def save_page(fields_list: list, today: str, now: Optional[datetime] = None) -> int:
    """Write one crawled page as today's snapshot. Returns the number written."""
    if not fields_list:
        return 0
    now = now or datetime.now()
    coll = products()
    ids = [fields["store_product_id"] for fields in fields_list]
    try:
        existing = {
            doc["_id"]: doc
            for doc in coll.find({"_id": {"$in": ids}}, {"price_history": 1, "name": 1, "brand": 1, "category_path": 1})
        }
        operations = []
        for fields in fields_list:
            product_id = fields["store_product_id"]
            previous = existing.get(product_id)
            price_set = dict(fields["prices"])
            row = offers.history_row(today, price_set, fields["availability"])
            history = _merge_history(previous.get("price_history") if previous else None, today, row)
            current = {key: history[-1].get(key) for key in ("date", "regular", "promo", "loyalty", "unit_price", "unit")}
            text_changed = previous is None or any(previous.get(k) != fields.get(k) for k in _TEXT_FIELDS)

            document = {key: value for key, value in fields.items() if key not in ("prices", "store_product_id")}
            document.update({
                "price_history": history,
                "current": current,
                "browse_sort": browse_sort_fields(current),
                "last_seen": now,
                "updated_at": now,
            })
            if text_changed:
                document["needs_details"] = True
                document["needs_revector"] = True
            operations.append(UpdateOne(
                {"_id": product_id},
                {"$set": document, "$setOnInsert": {"first_seen": now}},
                upsert=True,
            ))
        result = coll.bulk_write(operations, ordered=False)
        return result.upserted_count + result.matched_count
    except mongo_errors.PyMongoError as exc:
        logger.exception("Failed to save an Auchan page")
        raise RepositoryError("failed to save Auchan products") from exc


def products_needing_details(limit: int) -> list:
    return list(products().find({"needs_details": True}, {"_id": 1, "variant_id": 1}).limit(limit))


def save_details(product_id: str, text: dict, now: Optional[datetime] = None) -> None:
    update = {"needs_details": False, "details_fetched_at": now or datetime.now()}
    update.update({key: value for key, value in text.items() if key in ("description", "ingredients")})
    products().update_one({"_id": product_id}, {"$set": update, "$unset": {"details_error": ""}})


def mark_details_failed(product_id: str, reason: str) -> None:
    products().update_one({"_id": product_id}, {"$set": {"needs_details": False, "details_error": reason[:300]}})


# -- run state ------------------------------------------------------------------

def load_run(date: str) -> Optional[dict]:
    try:
        return runs().find_one({"_id": date})
    except mongo_errors.PyMongoError as exc:
        raise RepositoryError("failed to read Auchan run state") from exc


def save_run(state: dict) -> None:
    state["_id"] = state["date"]
    try:
        runs().replace_one({"_id": state["_id"]}, state, upsert=True)
    except mongo_errors.PyMongoError as exc:
        raise RepositoryError("failed to write Auchan run state") from exc


def latest_run() -> Optional[dict]:
    try:
        return runs().find_one(sort=[("_id", DESCENDING)])
    except mongo_errors.PyMongoError as exc:
        raise RepositoryError("failed to read Auchan run state") from exc
