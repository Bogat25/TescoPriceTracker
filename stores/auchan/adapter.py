"""Read adapter for Auchan documents in ``auchan_products``."""

from typing import Optional

from stores import offers
from stores.auchan import mapper, repository
from stores.browse import browse_sort_spec, text_search


STORE_ID = mapper.STORE_ID

_OFFER_PROJECTION = {"price_history": 0, "description": 0, "ingredients": 0}


def get_offer(store_product_id: str) -> Optional[dict]:
    doc = repository.products().find_one({"_id": str(store_product_id)}, _OFFER_PROJECTION)
    return mapper.offer_from_doc(doc) if doc else None


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


def browse(limit: int, sort_by: str, sort_dir: str) -> dict:
    coll = repository.products()
    cursor = coll.find({}, _OFFER_PROJECTION).sort(browse_sort_spec(sort_by, sort_dir)).limit(limit)
    return {
        "results": [mapper.offer_from_doc(doc) for doc in cursor],
        "total": coll.estimated_document_count(),
    }
