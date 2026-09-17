"""Queries across one or more stores.

Results are rows: one row per product group (same barcode) holding every
requested store's offer, or one row per unlinkable offer. Stores are queried
one by one and merged without favouring any store: search results interleave
by their rank within each store, browse results merge by the sort key. Offers
of a linked product that did not appear in another store's result window are
filled in by barcode, so a row shows every requested store that sells it.
"""

import logging
from typing import Optional

from stores import tesco
from stores.auchan import adapter as auchan
from stores.browse import SORT_FIELDS
from stores.ids import parse_ref
from stores.offers import parse_group_id


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


# -- rows -----------------------------------------------------------------------

def _price_key(offer: dict, store_order: dict):
    price = offer.get("effective_price")
    return (price is None, price if price is not None else 0.0, store_order.get(offer["store"], 99))


def make_row(offers: list, store_ids: list) -> dict:
    """One product row. Offers are ordered cheapest first."""
    store_order = {store_id: index for index, store_id in enumerate(store_ids)}
    unique = {offer["ref"]: offer for offer in offers}
    ordered = sorted(unique.values(), key=lambda offer: _price_key(offer, store_order))
    # Display fields come from the first store in registry order, so a row's
    # name and image do not flip between stores as prices change.
    display = min(ordered, key=lambda offer: (store_order.get(offer["store"], 99), offer["ref"]))
    prices = [offer["effective_price"] for offer in ordered if offer.get("effective_price") is not None]
    best = min(prices) if prices else None
    return {
        "group_id": display.get("group_id"),
        "gtin": display.get("gtin"),
        "name": display.get("name"),
        "brand": display.get("brand"),
        "image_url": next((offer["image_url"] for offer in ordered if offer.get("image_url")), None),
        "best_price": best,
        "cheapest_stores": sorted({o["store"] for o in ordered if best is not None and o.get("effective_price") == best},
                                  key=lambda store: store_order.get(store, 99)),
        "store_count": len({offer["store"] for offer in ordered}),
        "offers": ordered,
    }


def _group_in_order(offers: list) -> list:
    """Group offers by product, keeping the position of each group's first offer."""
    groups: dict = {}
    for offer in offers:
        key = offer.get("group_id") or offer["ref"]
        groups.setdefault(key, []).append(offer)
    return list(groups.values())


def _fill_missing_stores(groups: list, store_ids: list) -> None:
    """Add offers of linked products from requested stores missing in a group."""
    wanted: dict = {}
    for offers in groups:
        gtin = offers[0].get("gtin") if offers[0].get("group_id") else None
        if not gtin:
            continue
        present = {offer["store"] for offer in offers}
        for store_id in store_ids:
            if store_id not in present:
                wanted.setdefault(store_id, set()).add(gtin)
    if not wanted:
        return
    by_gtin: dict = {}
    for store_id, gtins in wanted.items():
        for offer in adapter_for(store_id).find_by_gtins(sorted(gtins)):
            by_gtin.setdefault(offer["gtin"], []).append(offer)
    for offers in groups:
        if offers[0].get("group_id"):
            present = {offer["store"] for offer in offers}
            offers.extend(o for o in by_gtin.get(offers[0]["gtin"], []) if o["store"] not in present)


def search(store_ids: list, query: str, skip: int, limit: int) -> dict:
    window = _window(skip, limit)
    ranked = []
    total = 0
    for order, store_id in enumerate(store_ids):
        page = adapter_for(store_id).search(query, window)
        total += page["total"]
        ranked.extend((rank, order, offer) for rank, offer in enumerate(page["results"]))
    ranked.sort(key=lambda item: (item[0], item[1]))
    groups = _group_in_order([offer for _, _, offer in ranked])[skip:skip + limit]
    _fill_missing_stores(groups, store_ids)
    return {
        "results": [make_row(offers, store_ids) for offers in groups],
        "total": total,
        "total_counts_offers": True,
        "skip": skip,
        "limit": limit,
        "stores": store_ids,
    }


def _row_sort_key(sort_by: str, descending: bool):
    def key(row):
        offers = row["offers"]
        name = (row.get("name") or "").casefold()
        if sort_by == "name":
            return name
        if sort_by == "price":
            value = row["best_price"]
        else:
            value = max((offer["discount_ratio"] for offer in offers), default=0.0) or None
        # Rows without a value always sort last, whichever direction.
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
    key = _row_sort_key(sort_by, descending)
    reverse = descending and sort_by == "name"
    # Order offers as single-offer rows first, so each group sits where its
    # best-placed offer would; then fill in missing stores and order the page.
    merged.sort(key=lambda offer: key(make_row([offer], store_ids)), reverse=reverse)
    groups = _group_in_order(merged)[skip:skip + limit]
    _fill_missing_stores(groups, store_ids)
    rows = sorted((make_row(offers, store_ids) for offers in groups), key=key, reverse=reverse)
    return {
        "results": rows,
        "total": total,
        "total_counts_offers": True,
        "skip": skip,
        "limit": limit,
        "stores": store_ids,
    }


# -- single offers and groups ---------------------------------------------------------

def get_offer(ref: str) -> Optional[dict]:
    store_id, store_product_id = parse_ref(ref)
    return adapter_for(store_id).get_offer(store_product_id)


def get_history(ref: str) -> Optional[list]:
    store_id, store_product_id = parse_ref(ref)
    return adapter_for(store_id).get_history(store_product_id)


def get_group(group_id: str, store_ids: list) -> Optional[dict]:
    gtin = parse_group_id(group_id)
    if gtin is None:
        return None
    offers = [offer for store_id in store_ids for offer in adapter_for(store_id).find_by_gtins([gtin])]
    if not offers:
        return None
    return make_row(offers, store_ids)


def get_group_history(group_id: str, store_ids: list) -> Optional[dict]:
    row = get_group(group_id, store_ids)
    if row is None:
        return None
    series = []
    for offer in row["offers"]:
        history = get_history(offer["ref"]) or []
        series.append({"store": offer["store"], "ref": offer["ref"], "history": history})
    series.sort(key=lambda item: (store_ids.index(item["store"]), item["ref"]))
    return {"group_id": row["group_id"], "series": series}
