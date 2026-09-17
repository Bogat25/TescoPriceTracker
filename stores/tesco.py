"""Read adapter for Tesco documents in the existing ``products`` collection.

The stored shape is not changed: ``normal``/``discount``/``clubcard`` history
entries are mapped to ``regular``/``promo``/``loyalty`` when they are read.
"""

from typing import Optional

from mongo import database_manager as db
from stores import offers
from stores.browse import browse_sort_spec, text_search


STORE_ID = "tesco"
PRODUCT_URL = "https://bevasarlas.tesco.hu/shop/hu-HU/products/{}"

# Heavy fields no list or offer view needs; history keeps only the newest day.
_OFFER_PROJECTION = {
    "_id": 1, "name": 1, "gtin": 1, "brand_name": 1, "default_image_url": 1,
    "super_department_name": 1, "department_name": 1, "aisle_name": 1, "shelf_name": 1,
    "pack_size_value": 1, "pack_size_unit": 1, "is_for_sale": 1, "last_scraped_price": 1,
    "browse_sort": 1, "price_history": {"$slice": -1},
}


def _collection():
    return db.get_db()


def _price_set(details: dict) -> dict:
    return offers.prices(
        regular=details.get("last_scraped_price"),
        promo=details.get("discount_price"),
        loyalty=details.get("clubcard_price"),
        unit_price=details.get("unit_price"),
        unit=details.get("unit_measure"),
    )


def _latest_date(doc: dict) -> Optional[str]:
    history = doc.get("price_history")
    if isinstance(history, list):
        dates = [entry.get("date") for entry in history if isinstance(entry, dict) and entry.get("date")]
        if dates:
            return max(dates)
    scraped = doc.get("last_scraped_price")
    return scraped[:10] if isinstance(scraped, str) and len(scraped) >= 10 else None


def offer_from_doc(doc: dict) -> dict:
    details = (doc.get("browse_sort") or {}).get("details")
    if details is None:
        details = db._extract_price_details(doc)
    product_id = str(doc.get("tpnc") or doc["_id"])
    return offers.build_offer(
        store_id=STORE_ID,
        store_product_id=product_id,
        name=doc.get("name"),
        gtin=doc.get("gtin"),
        brand=doc.get("brand_name"),
        image_url=doc.get("default_image_url"),
        category_path=[doc.get(field) for field in
                       ("super_department_name", "department_name", "aisle_name", "shelf_name")],
        pack_size=doc.get("pack_size_value"),
        pack_unit=doc.get("pack_size_unit"),
        availability="unavailable" if doc.get("is_for_sale") is False else "available",
        price_set=_price_set(details),
        price_date=_latest_date(doc),
        url=PRODUCT_URL.format(product_id),
    )


def _bucket_price(bucket) -> Optional[dict]:
    return bucket if isinstance(bucket, dict) else None


def history_from_doc(doc: dict) -> list:
    rows = []
    for entry in doc.get("price_history") or []:
        if not isinstance(entry, dict) or not entry.get("date"):
            continue
        normal = _bucket_price(entry.get("normal")) or {}
        discount = _bucket_price(entry.get("discount")) or {}
        clubcard = _bucket_price(entry.get("clubcard")) or {}
        rows.append(offers.history_row(entry["date"], offers.prices(
            regular=normal.get("price"),
            promo=discount.get("price"),
            loyalty=clubcard.get("price"),
            unit_price=normal.get("unit_price"),
            unit=normal.get("unit_measure"),
        )))
    return sorted(rows, key=lambda row: row["date"])


def _text(value) -> Optional[str]:
    if isinstance(value, list):
        value = " ".join(str(part) for part in value if part)
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_offer(store_product_id: str) -> Optional[dict]:
    """One offer with its description and ingredients (list views leave them out)."""
    projection = dict(_OFFER_PROJECTION, product_marketing=1, marketing=1, short_description=1, ingredients=1)
    doc = _collection().find_one({"_id": str(store_product_id)}, projection)
    if not doc:
        return None
    offer = offer_from_doc(doc)
    offer["description"] = _text(doc.get("product_marketing")) or _text(doc.get("marketing")) or _text(doc.get("short_description"))
    offer["ingredients"] = _text(doc.get("ingredients"))
    return offer


def get_history(store_product_id: str) -> Optional[list]:
    doc = _collection().find_one({"_id": str(store_product_id)}, {"price_history": 1})
    return history_from_doc(doc) if doc else None


def search(query: str, limit: int) -> dict:
    docs = text_search(_collection(), query, limit, _OFFER_PROJECTION)
    return {"results": [offer_from_doc(doc) for doc in docs], "total": len(docs)}


def find_by_gtins(gtin_norms: list) -> list:
    if not gtin_norms:
        return []
    cursor = _collection().find({"gtin_norm": {"$in": list(gtin_norms)}}, _OFFER_PROJECTION)
    return [offer_from_doc(doc) for doc in cursor]


def _price(bucket) -> Optional[float]:
    if isinstance(bucket, dict):
        value = bucket.get("price")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def iter_histories(gtin_norms: Optional[list] = None):
    """Yield ``(ref, name, category, gtin_norm, rows)`` for statistics.

    ``rows`` are ``(date, regular, promo, loyalty)`` tuples, oldest first; kept
    as tuples because a pass reads every day of every product.
    """
    query = {"gtin_norm": {"$in": list(gtin_norms)}} if gtin_norms is not None else {}
    projection = {"name": 1, "super_department_name": 1, "gtin_norm": 1, "price_history": 1}
    for doc in _collection().find(query, projection, batch_size=500):
        history = doc.get("price_history")
        if not isinstance(history, list):
            continue
        rows = sorted((
            (entry["date"], _price(entry.get("normal")), _price(entry.get("discount")), _price(entry.get("clubcard")))
            for entry in history
            if isinstance(entry, dict) and entry.get("date")
        ), key=lambda row: row[0])
        yield f"{STORE_ID}:{doc['_id']}", doc.get("name"), doc.get("super_department_name"), doc.get("gtin_norm"), rows


def browse(limit: int, sort_by: str, sort_dir: str) -> dict:
    collection = _collection()
    cursor = collection.find({}, _OFFER_PROJECTION).sort(browse_sort_spec(sort_by, sort_dir)).limit(limit)
    return {
        "results": [offer_from_doc(doc) for doc in cursor],
        "total": collection.estimated_document_count(),
    }
