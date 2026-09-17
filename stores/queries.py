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

from stores import semantic, tesco
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


SEARCH_MODES = ("hybrid", "semantic", "text")
RRF_K = 60            # Reciprocal Rank Fusion constant (Cormack et al., 2009)
CANDIDATES_MAX = 200  # per store and per retriever; the text index also stops at 200


def _page(ranked_offers: list, total: int, store_ids: list, skip: int, limit: int, mode: str) -> dict:
    groups = _group_in_order(ranked_offers)[skip:skip + limit]
    _fill_missing_stores(groups, store_ids)
    return {
        "results": [make_row(offers, store_ids) for offers in groups],
        "total": total,
        "total_counts_offers": True,
        "skip": skip,
        "limit": limit,
        "stores": store_ids,
        "mode": mode,
    }


def _interleave(lists_by_store: list) -> list:
    """Merge per-store rankings by rank, so no store is favoured."""
    ranked = [(rank, order, offer) for order, offers in enumerate(lists_by_store) for rank, offer in enumerate(offers)]
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [offer for _, _, offer in ranked]


def _semantic_offers(store_id: str, vector: list, window: int, min_score: float) -> list:
    hits = semantic.nearest(vector, [store_id], window, min_score=min_score)
    ids = [parse_ref(ref)[1] for ref, _ in hits]
    return adapter_for(store_id).find_by_ids(ids)


def fuse(rankings: list) -> list:
    """Reciprocal Rank Fusion of several rankings of the same store's offers.

    Each offer scores ``sum(1 / (RRF_K + rank))`` over the rankings it appears
    in (rank starts at 1). Only ranks are used, so the text score and the
    cosine similarity never need to be put on the same scale.
    """
    scores: dict = {}
    offers_by_ref: dict = {}
    first_seen: dict = {}
    for ranking in rankings:
        for rank, offer in enumerate(ranking, start=1):
            ref = offer["ref"]
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (RRF_K + rank)
            offers_by_ref.setdefault(ref, offer)
            first_seen.setdefault(ref, len(first_seen))
    order = sorted(scores, key=lambda ref: (-scores[ref], first_seen[ref]))
    return [offers_by_ref[ref] for ref in order]


def _is_code(query: str) -> bool:
    """Barcodes and product IDs: only an exact text match makes sense."""
    return query.replace(" ", "").isdigit()


def search(store_ids: list, query: str, skip: int, limit: int, mode: str = "text",
           min_score: Optional[float] = None) -> dict:
    """``min_score`` overrides ``SEMANTIC_MIN_SCORE`` (used by scripts/search_eval.py to calibrate it)."""
    if mode not in SEARCH_MODES:
        raise ValueError(f"mode must be one of {SEARCH_MODES}")
    window = _window(skip, limit)
    if mode != "text" and not _is_code(query):
        try:
            threshold = semantic.MIN_SCORE if min_score is None else min_score
            return _semantic_search(store_ids, query, skip, limit, mode, min(window, CANDIDATES_MAX), threshold)
        except semantic.SemanticUnavailable as exc:
            logger.warning(
                "Semantic search unavailable, answering with text search: %s", exc,
                extra={"Action": "search.semantic_unavailable", "Category": "search"},
            )

    text_lists = []
    total = 0
    for store_id in store_ids:
        page = adapter_for(store_id).search(query, window)
        total += page["total"]
        text_lists.append(page["results"])
    return _page(_interleave(text_lists), total, store_ids, skip, limit, "text")


def _semantic_search(store_ids: list, query: str, skip: int, limit: int, mode: str, window: int, min_score: float) -> dict:
    vector = semantic.embed_query(query)
    per_store = []
    for store_id in store_ids:
        semantic_offers = _semantic_offers(store_id, vector, window, min_score)
        if mode == "semantic":
            per_store.append(semantic_offers)
        else:
            text_offers = adapter_for(store_id).search(query, window)["results"]
            per_store.append(fuse([text_offers, semantic_offers]))
    ranked = _interleave(per_store)
    return _page(ranked, len(ranked), store_ids, skip, limit, mode)


def similar(store_ids: list, limit: int, ref: Optional[str] = None, group_id: Optional[str] = None) -> Optional[dict]:
    """Products whose descriptions are closest to an offer's or a group's.

    The product's own group is left out, so the list never repeats the same
    product from another store. Returns None when the product has no vector yet.
    """
    if group_id:
        gtin = parse_group_id(group_id)
        if gtin is None:
            return None
        refs = [offer["ref"] for store_id in ADAPTERS for offer in adapter_for(store_id).find_by_gtins([gtin])]
    else:
        store_id, product_id = parse_ref(ref)
        found = adapter_for(store_id).find_by_ids([product_id])
        if not found:
            return None
        refs = [ref]
        group_id = found[0].get("group_id")
    vectors = semantic.vectors_for(refs)
    if not vectors:
        return None
    hits = semantic.nearest(semantic.mean_vector(list(vectors.values())), store_ids, limit * 4,
                            exclude_group=group_id, exclude_ref=None if group_id else ref)
    by_store: dict = {}
    for hit_ref, _ in hits:
        hit_store, hit_id = parse_ref(hit_ref)
        by_store.setdefault(hit_store, []).append(hit_id)
    offers_by_ref = {offer["ref"]: offer for store_id, ids in by_store.items() for offer in adapter_for(store_id).find_by_ids(ids)}
    ranked = [offers_by_ref[hit_ref] for hit_ref, _ in hits if hit_ref in offers_by_ref]
    groups = _group_in_order(ranked)[:limit]
    _fill_missing_stores(groups, store_ids)
    return {"results": [make_row(offers, store_ids) for offers in groups], "stores": store_ids}


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
