from datetime import datetime
from pymongo import MongoClient
from pymongo import errors as mongo_errors
import logging

from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

logger = logging.getLogger(__name__)

# Mongo Setup
_client = None
_db = None
_collection = None

def get_db():
    global _client, _db, _collection
    if _client is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[MONGO_DB_NAME]
        _collection = _db[MONGO_COLLECTION]
    return _collection

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
    _db['runs'].create_index("_id")
    print("MongoDB indexes verified/created.")

def load_product_data(tpnc):
    try:
        coll = get_db()
        return coll.find_one({"_id": str(tpnc)})
    except mongo_errors.PyMongoError as e:
        logger.error(f"Error loading product {tpnc}: {e}")
        return None

def save_product_data(tpnc, data):
    try:
        coll = get_db()
        data['_id'] = str(tpnc)
        coll.replace_one({"_id": str(tpnc)}, data, upsert=True)
    except mongo_errors.PyMongoError as e:
        logger.error(f"Error saving product {tpnc}: {e}")

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

    for category, fields in price_updates:
        today_entry[category] = dict(fields)

    if metadata:
        data.update(metadata)

    data["last_scraped_price"] = datetime.now().isoformat()
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


def _extract_current_price(doc: dict):
    """Return the most recent normal price from a product document, or None."""
    history = doc.get("price_history", [])
    if not isinstance(history, list) or not history:
        return None
    # history is stored oldest-first; take the last entry with a normal price
    for entry in reversed(history):
        if isinstance(entry, dict):
            normal = entry.get("normal")
            if normal and normal.get("price") is not None:
                return normal["price"]
    return None


def browse_products(skip=0, limit=100):
    """Return lightweight product summaries for the catalogue view.

    Projects only the fields needed by the frontend list (no price_history).

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
        "price_history": 1,
    }
    cursor = coll.find({}, projection).sort("name", 1).skip(skip).limit(limit)
    results = []
    for doc in cursor:
        tpnc = str(doc.get("tpnc") or doc.get("_id") or "")
        doc.pop("_id", None)
        doc["tpnc"] = tpnc
        doc["last_scraped_price"] = _extract_current_price(doc)
        doc.pop("price_history", None)
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
        doc.pop("price_history", None)
        doc.pop("score", None)
        doc["last_scraped_price"] = _extract_current_price(doc)
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
        logger.error(f"Error reading cache key {key}: {e}")
        return None


def set_cached_stat(key: str, data) -> None:
    try:
        coll = get_stats_collection()
        coll.replace_one(
            {"_id": key},
            {"_id": key, "data": data, "computed_at": datetime.now().isoformat()},
            upsert=True,
        )
    except mongo_errors.PyMongoError as e:
        logger.error(f"Error writing cache key {key}: {e}")


# ---------------------------------------------------------------------------
# Run-state helpers (MongoDB-backed)
# ---------------------------------------------------------------------------

def load_run_state():
    try:
        coll = get_runs_collection()
        today_iso = datetime.now().date().isoformat()
        return coll.find_one({"_id": today_iso})
    except mongo_errors.PyMongoError as e:
        logger.warning(f"Failed to read run_state from mongo: {e}")
        return None

def save_run_state(state: dict):
    try:
        coll = get_runs_collection()
        state_id = state.get('date', datetime.now().date().isoformat())
        state['_id'] = state_id
        coll.replace_one({"_id": state_id}, state, upsert=True)
    except mongo_errors.PyMongoError as e:
        logger.error(f"Failed to write run_state to mongo: {e}")


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

    Each item: {productId, productName, oldPrice, newPrice}. Used by the scraper
    to invoke the alert-service after a daily run completes.
    """
    coll = get_db()
    assert coll is not None
    today_str = datetime.now().strftime("%Y-%m-%d")

    cursor = coll.find(
        {"price_history.date": today_str},
        {"_id": 1, "name": 1, "price_history": 1},
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
            "productId": str(doc["_id"]),
            "productName": doc.get("name"),
            "oldPrice": old_price,
            "newPrice": new_price,
        })
    return drops


