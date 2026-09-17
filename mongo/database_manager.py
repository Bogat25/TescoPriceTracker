from datetime import datetime
from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne
from pymongo import errors as mongo_errors
import logging

from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION
from stores.ids import normalize_gtin
from stores.offers import group_id_for

logger = logging.getLogger(__name__)

# These fields feed recomendation-system/data_preparation.py. Any change must
# invalidate the existing embedding so Mongo and Qdrant do not silently drift.
_EMBEDDING_SOURCE_FIELDS = {
    "name",
    "brand_name",
    "sub_brand",
    "super_department_name",
    "department_name",
    "aisle_name",
    "shelf_name",
    "short_description",
    "marketing",
    "product_marketing",
    "features",
    "nutritional_claims",
    "ingredients",
}

# Mongo Setup
_client = None
_db = None
_collection = None


class DatabaseOperationError(RuntimeError):
    """Raised when MongoDB could not durably complete a required operation."""

def get_db():
    global _client, _db, _collection
    if _client is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[MONGO_DB_NAME]
        _collection = _db[MONGO_COLLECTION]
    return _collection

def get_database():
    """The tracker database, for collections other than the Tesco products."""
    get_db()
    assert _db is not None
    return _db


def get_runs_collection():
    get_db()
    assert _db is not None
    return _db['runs']


def init_db():
    coll = get_db()
    coll.create_index([("name", "text")])
    coll.create_index("last_scraped_price")
    coll.create_index("super_department_name")
    coll.create_index("department_name")
    coll.create_index("aisle_name")
    coll.create_index("shelf_name")
    coll.create_index("brand_name")
    coll.create_index(
        [("browse_sort.has_price", DESCENDING), ("browse_sort.effective_price", ASCENDING), ("name", ASCENDING)],
        name="browse_price_asc",
    )
    coll.create_index(
        [("browse_sort.has_price", DESCENDING), ("browse_sort.effective_price", DESCENDING), ("name", ASCENDING)],
        name="browse_price_desc",
    )
    coll.create_index(
        [("browse_sort.has_discount", DESCENDING), ("browse_sort.discount_ratio", ASCENDING), ("name", ASCENDING)],
        name="browse_discount_asc",
    )
    coll.create_index(
        [("browse_sort.has_discount", DESCENDING), ("browse_sort.discount_ratio", DESCENDING), ("name", ASCENDING)],
        name="browse_discount_desc",
    )
    coll.create_index("gtin_norm", sparse=True)
    _db['runs'].create_index("_id")
    backfill_browse_sort_fields(coll)
    backfill_gtin_norm(coll)
    print("MongoDB indexes verified/created.")

def load_product_data(tpnc):
    try:
        coll = get_db()
        return coll.find_one({"_id": str(tpnc)})
    except mongo_errors.PyMongoError as e:
        logger.exception("Error loading product %s", tpnc)
        raise DatabaseOperationError(f"failed to load product {tpnc}") from e

def save_product_data(tpnc, data):
    try:
        coll = get_db()
        data['_id'] = str(tpnc)
        result = coll.replace_one({"_id": str(tpnc)}, data, upsert=True)
        if not result.acknowledged:
            raise DatabaseOperationError(f"unacknowledged save for product {tpnc}")
    except mongo_errors.PyMongoError as e:
        logger.exception("Error saving product %s", tpnc)
        raise DatabaseOperationError(f"failed to save product {tpnc}") from e

def product_exists(tpnc):
    coll = get_db()
    return coll.count_documents({"_id": str(tpnc)}, limit=1) > 0


# ---------------------------------------------------------------------------
# Daily price insertion logic
# ---------------------------------------------------------------------------

def insert_daily_prices(tpnc, price_updates, metadata=None):
    """Store prices for today as a daily snapshot.

    Parameters
    ----------
    tpnc : str
    price_updates : list of (category, fields) tuples
        category is "normal", "discount", or "clubcard".
    metadata : dict or None
        If provided, updates static product fields (name, unit_of_measure,
        default_image_url, pack_size_value, pack_size_unit).

    Returns
    -------
    dict: {category: bool} — True if a new day entry was created, False if updated.
    """
    data = load_product_data(tpnc)
    if not data:
        data = {"tpnc": str(tpnc), "price_history": []}

    history = data.setdefault("price_history", [])
    if isinstance(history, dict):
        history = []
        data["price_history"] = history

    today_str = datetime.now().strftime("%Y-%m-%d")

    # Find today's entry or create a blank one
    today_entry = None
    for entry in history:
        if isinstance(entry, dict) and entry.get("date") == today_str:
            today_entry = entry
            break

    is_new_day = today_entry is None
    if is_new_day:
        today_entry = {"date": today_str, "normal": None, "discount": None, "clubcard": None}
        history.append(today_entry)
    else:
        # A second scrape on the same day is a replacement snapshot. Clear
        # promotions that disappeared upstream instead of retaining stale data.
        today_entry.update({"normal": None, "discount": None, "clubcard": None})

    for category, fields in price_updates:
        today_entry[category] = dict(fields)

    if metadata:
        embedding_changed = any(
            data.get(field) != metadata.get(field)
            for field in _EMBEDDING_SOURCE_FIELDS
            if field in metadata
        )
        data.update(metadata)
        if embedding_changed and "vector_embedding" in data:
            data["needs_revector"] = True

    gtin_norm = normalize_gtin(data.get("gtin"))
    if gtin_norm:
        data["gtin_norm"] = gtin_norm

    data["last_scraped_price"] = datetime.now().isoformat()
    data["browse_sort"] = _build_browse_sort_fields(data)
    save_product_data(tpnc, data)

    return {category: is_new_day for category, _ in price_updates}


# ---------------------------------------------------------------------------
# Query helpers (used by app.py / frontend)
# ---------------------------------------------------------------------------

def get_product(tpnc):
    return load_product_data(tpnc)


def get_price_history(tpnc):
    data = load_product_data(tpnc)
    if not data:
        return []
    history = data.get("price_history", [])
    if isinstance(history, dict):
        return []
    # Return newest first
    return list(reversed(history))


def get_all_product_ids(skip=0, limit=100):
    """Return paginated list of all product TPNCs.

    Returns
    -------
    dict with keys: ids (list of str), total (int), skip (int), limit (int)
    """
    coll = get_db()
    assert coll is not None
    total = coll.count_documents({})
    cursor = coll.find({}, {"_id": 1}).skip(skip).limit(limit)
    ids = [doc["_id"] for doc in cursor]
    return {"ids": ids, "total": total, "skip": skip, "limit": limit}


def get_product_stats(tpnc):
    """Compute min/max/avg/current price per category across all daily history.

    Returns
    -------
    dict or None if product not found.
    """
    data = load_product_data(tpnc)
    if not data:
        return None

    history = data.get("price_history", [])
    if isinstance(history, dict):
        history = []

    stats = {}
    for category in ("normal", "discount", "clubcard"):
        prices = [
            entry[category]["price"]
            for entry in history
            if isinstance(entry, dict) and entry.get(category) and entry[category].get("price") is not None
        ]
        if not prices:
            stats[category] = None
        else:
            stats[category] = {
                "min_price": min(prices),
                "max_price": max(prices),
                "avg_price": round(sum(prices) / len(prices), 2),
                "current_price": prices[-1],  # history is oldest-first in storage
            }

    sorted_history = sorted(history, key=lambda e: e.get("date", "")) if isinstance(history, list) else []
    first_date = sorted_history[0]["date"] if sorted_history else None
    last_date = sorted_history[-1]["date"] if sorted_history else None

    return {
        "tpnc": str(tpnc),
        "name": data.get("name"),
        "total_days": len(history),
        "first_date": first_date,
        "last_date": last_date,
        "normal": stats["normal"],
        "discount": stats["discount"],
        "clubcard": stats["clubcard"],
    }


def _extract_price_details(doc: dict) -> dict:
    """Extract normal, discount, clubcard prices plus unit info from latest entry."""
    history = doc.get("price_history", [])
    if not isinstance(history, list) or not history:
        return {}
    result = {}
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        normal = entry.get("normal")
        if normal and normal.get("price") is not None:
            result["last_scraped_price"] = normal["price"]
            if normal.get("unit_price") is not None:
                result["unit_price"] = normal["unit_price"]
            if normal.get("unit_measure"):
                result["unit_measure"] = normal["unit_measure"]
        discount = entry.get("discount")
        if discount and discount.get("price") is not None:
            result["discount_price"] = discount["price"]
            if discount.get("promo_desc"):
                result["discount_desc"] = discount["promo_desc"]
        clubcard = entry.get("clubcard")
        if clubcard and clubcard.get("price") is not None:
            result["clubcard_price"] = clubcard["price"]
            if clubcard.get("promo_desc"):
                result["clubcard_desc"] = clubcard["promo_desc"]
        if "last_scraped_price" in result:
            break
    return result


def _build_browse_sort_fields(doc: dict) -> dict:
    """Denormalize current prices so catalogue sorting remains index-backed."""
    details = _extract_price_details(doc)
    candidates = [
        details.get("last_scraped_price"),
        details.get("discount_price"),
        details.get("clubcard_price"),
    ]
    numeric = [float(value) for value in candidates if isinstance(value, (int, float))]
    normal = details.get("last_scraped_price")
    discount = details.get("discount_price")
    has_discount = (
        isinstance(normal, (int, float))
        and normal > 0
        and isinstance(discount, (int, float))
        and discount < normal
    )
    ratio = float((normal - discount) / normal) if has_discount else 0.0
    return {
        "version": 1,
        "has_price": bool(numeric),
        "effective_price": min(numeric) if numeric else None,
        "has_discount": has_discount,
        "discount_ratio": ratio,
        "details": details,
    }


def backfill_browse_sort_fields(coll=None, batch_size: int = 500) -> int:
    """One-time, idempotent migration for documents created before v1 fields."""
    if coll is None:
        coll = get_db()
    cursor = coll.find(
        {"browse_sort.version": {"$ne": 1}},
        {"_id": 1, "price_history": 1},
    )
    operations = []
    updated = 0
    for doc in cursor:
        operations.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"browse_sort": _build_browse_sort_fields(doc)}},
        ))
        if len(operations) >= batch_size:
            result = coll.bulk_write(operations, ordered=False)
            updated += result.modified_count
            operations.clear()
    if operations:
        result = coll.bulk_write(operations, ordered=False)
        updated += result.modified_count
    if updated:
        logger.info("Backfilled indexed browse fields for %d products", updated)
    return updated


def backfill_gtin_norm(coll=None, batch_size: int = 500) -> int:
    """Idempotently add the cross-store barcode key to products saved before it."""
    if coll is None:
        coll = get_db()
    cursor = coll.find(
        {"gtin": {"$exists": True}, "gtin_norm": {"$exists": False}},
        {"_id": 1, "gtin": 1},
    )
    operations = []
    updated = 0
    for doc in cursor:
        gtin_norm = normalize_gtin(doc.get("gtin"))
        if not gtin_norm:
            continue
        operations.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"gtin_norm": gtin_norm}}))
        if len(operations) >= batch_size:
            updated += coll.bulk_write(operations, ordered=False).modified_count
            operations.clear()
    if operations:
        updated += coll.bulk_write(operations, ordered=False).modified_count
    if updated:
        logger.info("Backfilled normalised GTINs for %d products", updated)
    return updated


def browse_products(skip=0, limit=100, sort_by="name", sort_dir="asc"):
    """Return lightweight product summaries for the catalogue view.

    Projects only the fields needed by the frontend list (no price_history).
    Supports sort_by: "name" (default), "price" (normal price asc/desc),
    "discount" (by discount percentage desc).

    Returns
    -------
    dict with keys: results (list), total (int), skip (int), limit (int)
    """
    coll = get_db()
    total = coll.count_documents({})
    projection = {
        "_id": 1,
        "tpnc": 1,
        "name": 1,
        "default_image_url": 1,
        "unit_of_measure": 1,
        "pack_size_value": 1,
        "pack_size_unit": 1,
        "brand_name": 1,
        "super_department_name": 1,
        "department_name": 1,
        "overall_rating": 1,
        "number_of_reviews": 1,
        "browse_sort": 1,
    }

    # Every supported ordering is executed and paginated by MongoDB. Current
    # prices are denormalized during ingestion, so no request loads the catalog.
    if sort_by == "name":
        mongo_sort = [("name", ASCENDING if sort_dir == "asc" else DESCENDING)]
    elif sort_by == "price":
        direction = ASCENDING if sort_dir == "asc" else DESCENDING
        mongo_sort = [
            ("browse_sort.has_price", DESCENDING),
            ("browse_sort.effective_price", direction),
            ("name", ASCENDING),
        ]
    else:
        direction = ASCENDING if sort_dir == "asc" else DESCENDING
        mongo_sort = [
            ("browse_sort.has_discount", DESCENDING),
            ("browse_sort.discount_ratio", direction),
            ("name", ASCENDING),
        ]

    cursor = coll.find({}, projection).sort(mongo_sort).skip(skip).limit(limit)
    results = []
    for doc in cursor:
        tpnc = str(doc.get("tpnc") or doc.get("_id") or "")
        doc.pop("_id", None)
        doc["tpnc"] = tpnc
        browse_sort = doc.pop("browse_sort", {}) or {}
        doc.update(browse_sort.get("details", {}))
        results.append(doc)
    return {"results": results, "total": total, "skip": skip, "limit": limit}


def search_products(query, skip: int = 0, limit: int = 50):
    results = []
    if not query:
        return {"results": [], "total": 0, "skip": skip, "limit": limit}

    coll = get_db()
    SEARCH_MAX = 100

    # Try text index search first
    text_cursor = coll.find(
        {"$text": {"$search": query}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).limit(SEARCH_MAX)

    results = list(text_cursor)

    if not results:
        # Fallback to regex scan (handles Hungarian chars, TPNC, partial names)
        regex_query = {"$regex": query, "$options": "i"}
        results = list(coll.find({"$or": [{"name": regex_query}, {"_id": regex_query}]}).limit(SEARCH_MAX))

    total = len(results)
    page_docs = results[skip: skip + limit]

    # Inject current_price into each result and strip heavy fields
    cleaned = []
    for doc in page_docs:
        tpnc = str(doc.get("tpnc") or doc.get("_id") or "")
        doc["tpnc"] = tpnc
        doc.pop("_id", None)
        price_info = _extract_price_details(doc)
        doc.update(price_info)
        doc.pop("price_history", None)
        doc.pop("score", None)
        cleaned.append(doc)

    return {"results": cleaned, "total": total, "skip": skip, "limit": limit}


def search_products_with_category(
    query: str,
    super_department=None,
    department=None,
    skip: int = 0,
    limit: int = 64,
):
    """Full-text search with optional super_department / department filters.

    Used by the catalogue page so search results respect the active category pill.
    """
    if not query:
        return {"results": [], "total": 0, "skip": skip, "limit": limit}

    coll = get_db()
    SEARCH_MAX = 200

    # Build optional category filter
    cat_filter: dict = {}
    if super_department:
        cat_filter["super_department_name"] = super_department
    if department:
        cat_filter["department_name"] = department

    # Try MongoDB text-index search first
    text_query: dict = {"$text": {"$search": query}}
    if cat_filter:
        text_query.update(cat_filter)

    text_cursor = coll.find(
        text_query,
        {"score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(SEARCH_MAX)

    results = list(text_cursor)

    if not results:
        # Fallback: regex scan (handles Hungarian chars, TPNC, partial names)
        regex_q = {"$regex": query, "$options": "i"}
        regex_filter: dict = {"$or": [{"name": regex_q}, {"_id": regex_q}, {"tpnc": regex_q}]}
        combined: dict = {"$and": [regex_filter, cat_filter]} if cat_filter else regex_filter
        results = list(coll.find(combined).limit(SEARCH_MAX))

    total = len(results)
    page_docs = results[skip: skip + limit]

    cleaned = []
    for doc in page_docs:
        tpnc = str(doc.get("tpnc") or doc.get("_id") or "")
        doc["tpnc"] = tpnc
        doc.pop("_id", None)
        price_info = _extract_price_details(doc)
        doc.update(price_info)
        doc.pop("price_history", None)
        doc.pop("score", None)
        cleaned.append(doc)

    return {"results": cleaned, "total": total, "skip": skip, "limit": limit}


# ---------------------------------------------------------------------------
# Stats cache helpers
# ---------------------------------------------------------------------------

def get_stats_collection():
    get_db()
    assert _db is not None
    return _db['stats_cache']


def get_cached_stat(key: str):
    try:
        coll = get_stats_collection()
        doc = coll.find_one({"_id": key})
        return doc["data"] if doc else None
    except mongo_errors.PyMongoError as e:
        logger.exception("Error reading cache key %s", key)
        raise DatabaseOperationError(f"failed to read cache key {key}") from e


def set_cached_stat(key: str, data) -> None:
    try:
        coll = get_stats_collection()
        result = coll.replace_one(
            {"_id": key},
            {"_id": key, "data": data, "computed_at": datetime.now().isoformat()},
            upsert=True,
        )
        if not result.acknowledged:
            raise DatabaseOperationError(f"unacknowledged cache write for {key}")
    except mongo_errors.PyMongoError as e:
        logger.exception("Error writing cache key %s", key)
        raise DatabaseOperationError(f"failed to write cache key {key}") from e


# ---------------------------------------------------------------------------
# Run-state helpers (MongoDB-backed)
# ---------------------------------------------------------------------------

def load_run_state():
    try:
        coll = get_runs_collection()
        today_iso = datetime.now().date().isoformat()
        return coll.find_one({"_id": today_iso})
    except mongo_errors.PyMongoError as e:
        logger.exception("Failed to read run_state from MongoDB")
        raise DatabaseOperationError("failed to read run state") from e

def load_latest_run_state():
    """Most recent run state by date, so a pass that began yesterday stays visible."""
    try:
        coll = get_runs_collection()
        return coll.find_one(sort=[("_id", DESCENDING)])
    except mongo_errors.PyMongoError as e:
        logger.exception("Failed to read the latest run_state from MongoDB")
        raise DatabaseOperationError("failed to read run state") from e

def save_run_state(state: dict):
    try:
        coll = get_runs_collection()
        state_id = state.get('date', datetime.now().date().isoformat())
        state['_id'] = state_id
        result = coll.replace_one({"_id": state_id}, state, upsert=True)
        if not result.acknowledged:
            raise DatabaseOperationError("unacknowledged run-state write")
    except mongo_errors.PyMongoError as e:
        logger.exception("Failed to write run_state to MongoDB")
        raise DatabaseOperationError("failed to write run state") from e


# ---------------------------------------------------------------------------
# Price-drop discovery (used by the alert-service trigger)
# ---------------------------------------------------------------------------

def _effective_price(entry: dict | None):
    """Pick the price a customer would actually pay: clubcard > discount > normal."""
    if not entry:
        return None
    for key in ("clubcard", "discount", "normal"):
        bucket = entry.get(key)
        if isinstance(bucket, dict):
            price = bucket.get("price")
            if isinstance(price, (int, float)):
                return float(price)
    return None


def get_today_price_drops() -> list:
    """Return products whose effective price today is lower than the prior day.

    Each item: {productId (offer reference), store, groupId, productName,
    oldPrice, newPrice}. Used by the scraper
    to invoke the alert-service after a daily run completes.
    """
    coll = get_db()
    assert coll is not None
    today_str = datetime.now().strftime("%Y-%m-%d")

    cursor = coll.find(
        {"price_history.date": today_str},
        {"_id": 1, "name": 1, "price_history": 1, "gtin_norm": 1},
    )

    drops: list[dict] = []
    for doc in cursor:
        history = doc.get("price_history") or []
        if not isinstance(history, list):
            continue

        sorted_history = sorted(
            (e for e in history if isinstance(e, dict) and e.get("date")),
            key=lambda e: e["date"],
        )
        if len(sorted_history) < 2 or sorted_history[-1]["date"] != today_str:
            continue

        new_price = _effective_price(sorted_history[-1])
        old_price = _effective_price(sorted_history[-2])
        if new_price is None or old_price is None:
            continue
        if new_price >= old_price:
            continue

        drops.append({
            "productId": f"tesco:{doc['_id']}",
            "store": "tesco",
            "groupId": group_id_for(doc.get("gtin_norm")),
            "productName": doc.get("name"),
            "oldPrice": old_price,
            "newPrice": new_price,
        })
    return drops


