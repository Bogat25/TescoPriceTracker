"""Read adapter for Auchan documents in ``auchan_products``."""

from typing import Optional

from stores import offers
from stores.auchan import mapper, repository
from stores.browse import browse_sort_spec, text_search


STORE_ID = mapper.STORE_ID

_OFFER_PROJECTION = {"price_history": 0, "description": 0, "ingredients": 0}


def get_offer(store_product_id: str) -> Optional[dict]:
    """One offer with its description and ingredients (list views leave them out)."""
    doc = repository.products().find_one({"_id": str(store_product_id)}, {"price_history": 0})
    if not doc:
        return None
    offer = mapper.offer_from_doc(doc)
    offer["description"] = doc.get("description")
    offer["ingredients"] = doc.get("ingredients")
    return offer


def get_history(store_product_id: str) -> Optional[list]:
    doc = repository.products().find_one({"_id": str(store_product_id)}, {"price_history": 1})
    if not doc:
        return None
    rows = []
    for entry in doc.get("price_history") or []:
        if isinstance(entry, dict) and entry.get("date"):
            price_set = offers.prices(**{k: entry.get(k) for k in ("regular", "promo", "loyalty", "unit_price", "unit")})
            rows.append(offers.history_row(entry["date"], price_set, entry.get("availability")))
    return rows


def search(query: str, limit: int) -> dict:
    docs = text_search(repository.products(), query, limit, _OFFER_PROJECTION, id_fields=("_id", "ean"))
    return {"results": [mapper.offer_from_doc(doc) for doc in docs], "total": len(docs)}


def find_by_ids(product_ids: list) -> list:
    """Offers for these product IDs, in the given order."""
    if not product_ids:
        return []
    docs = {doc["_id"]: doc for doc in repository.products().find({"_id": {"$in": [str(i) for i in product_ids]}}, _OFFER_PROJECTION)}
    return [mapper.offer_from_doc(docs[str(i)]) for i in product_ids if str(i) in docs]


def find_by_gtins(gtin_norms: list) -> list:
    if not gtin_norms:
        return []
    cursor = repository.products().find({"gtin_norm": {"$in": list(gtin_norms)}}, _OFFER_PROJECTION)
    return [mapper.offer_from_doc(doc) for doc in cursor]


def iter_histories(gtin_norms: Optional[list] = None):
    """Yield ``(ref, name, category, gtin_norm, rows)``; rows are ``(date, regular, promo, loyalty)``."""
    query = {"gtin_norm": {"$in": list(gtin_norms)}} if gtin_norms is not None else {}
    projection = {"name": 1, "category_path": 1, "gtin_norm": 1, "price_history": 1}
    for doc in repository.products().find(query, projection, batch_size=500):
        rows = sorted((
            (entry["date"], entry.get("regular"), entry.get("promo"), entry.get("loyalty"))
            for entry in doc.get("price_history") or []
            if isinstance(entry, dict) and entry.get("date")
        ), key=lambda row: row[0])
        categories = doc.get("category_path") or [None]
        yield f"{STORE_ID}:{doc['_id']}", doc.get("name"), categories[0], doc.get("gtin_norm"), rows


def browse(limit: int, sort_by: str, sort_dir: str) -> dict:
    coll = repository.products()
    cursor = coll.find({}, _OFFER_PROJECTION).sort(browse_sort_spec(sort_by, sort_dir)).limit(limit)
    return {
        "results": [mapper.offer_from_doc(doc) for doc in cursor],
        "total": coll.estimated_document_count(),
    }
