"""Queries across one or more stores.

A single store is queried directly. Several stores are queried one by one and
merged without favouring any store: search results are interleaved by their
rank within each store, browse results are merged by the requested sort key.
"""

import logging
from typing import Optional

from stores import tesco
from stores.auchan import adapter as auchan
from stores.browse import SORT_FIELDS
from stores.ids import parse_ref


logger = logging.getLogger(__name__)

ADAPTERS = {tesco.STORE_ID: tesco, auchan.STORE_ID: auchan}
MAX_WINDOW = 1000  # skip + limit; deeper pages would load too much per store


class WindowTooLarge(ValueError):
    pass


def adapter_for(store_id: str):
    return ADAPTERS[store_id]


def _window(skip: int, limit: int) -> int:
    if skip + limit > MAX_WINDOW:
        raise WindowTooLarge(f"skip + limit must not exceed {MAX_WINDOW}")
    return skip + limit


def get_offer(ref: str) -> Optional[dict]:
    store_id, store_product_id = parse_ref(ref)
    return adapter_for(store_id).get_offer(store_product_id)


def get_history(ref: str) -> Optional[list]:
    store_id, store_product_id = parse_ref(ref)
    return adapter_for(store_id).get_history(store_product_id)


def search(store_ids: list, query: str, skip: int, limit: int) -> dict:
    window = _window(skip, limit)
    ranked = []
    total = 0
    for order, store_id in enumerate(store_ids):
        page = adapter_for(store_id).search(query, window)
        total += page["total"]
        ranked.extend((rank, order, offer) for rank, offer in enumerate(page["results"]))
    ranked.sort(key=lambda item: (item[0], item[1]))
    results = [offer for _, _, offer in ranked][skip:skip + limit]
    return {"results": results, "total": total, "skip": skip, "limit": limit, "stores": store_ids}


def _sort_key(sort_by: str, descending: bool):
    def key(offer):
        name = (offer.get("name") or "").casefold()
        if sort_by == "name":
            return name
        value = offer["effective_price"] if sort_by == "price" else offer["discount_ratio"]
        if sort_by == "discount" and not value:
            value = None
        # Products without a value always sort last, whichever direction.
        if value is None:
            return (1, 0.0, name)
        return (0, -value if descending else value, name)
    return key


def browse(store_ids: list, skip: int, limit: int, sort_by: str = "name", sort_dir: str = "asc") -> dict:
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"sort_by must be one of {SORT_FIELDS}")
    window = _window(skip, limit)
    merged = []
    total = 0
    for store_id in store_ids:
        page = adapter_for(store_id).browse(window, sort_by, sort_dir)
        total += page["total"]
        merged.extend(page["results"])
    descending = sort_dir == "desc"
    merged.sort(key=_sort_key(sort_by, descending), reverse=descending and sort_by == "name")
    return {"results": merged[skip:skip + limit], "total": total, "skip": skip, "limit": limit, "stores": store_ids}
