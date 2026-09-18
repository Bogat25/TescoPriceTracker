"""Store-aware recommendation rows.

Personal picks come from what the user already watches: the alerted products
are grouped into the shared categories, and each group's mean vector finds
similar products in every selected store. A product sold by several stores is
one pick, shown with each store's price, so a recommendation is about a product
rather than about a listing.

Remaining slots are filled with the biggest current discounts across the
selected stores, which is also the whole answer for a visitor with no alerts.
"""

import logging
from typing import Optional

from stores import categories, queries, semantic
from stores.ids import parse_ref


logger = logging.getLogger(__name__)

TOP_CATEGORIES = 5
OVERSEARCH = 2.5          # candidates per slot, before category and watch filtering
SIMILARITY_WEIGHT = 0.5   # the rest is the discount; a pick should be relevant and worth buying
UNCATEGORISED = ""


def _row_key(row: dict) -> str:
    return row["group_id"] or row["offers"][0]["ref"]


# -- what the user watches ----------------------------------------------------------

def watched_offers(alerts: list, store_ids: list) -> list:
    """``(offer, created_at)`` for every alert target, in every selected store.

    An alert watches a barcode group (``g:{gtin}``), one store's listing
    (``auchan:123``) or, on alerts stored before targets existed, a bare Tesco
    product id.
    """
    by_gtin: dict = {}
    by_ref: dict = {}
    for alert in alerts:
        target = str(alert.get("target") or alert.get("productId") or "")
        created_at = alert.get("createdAt")
        if target.startswith("g:"):
            by_gtin.setdefault(target[2:], created_at)
        elif ":" in target:
            store_id, _ = _safe_ref(target)
            if store_id in store_ids:
                by_ref.setdefault(target, created_at)
        elif target:
            by_ref.setdefault(f"tesco:{target}", created_at)

    found = []
    for store_id in store_ids:
        adapter = queries.adapter_for(store_id)
        refs = [ref for ref in by_ref if ref.startswith(f"{store_id}:")]
        if refs:
            for offer in adapter.find_by_ids([ref.split(":", 1)[1] for ref in refs]):
                found.append((offer, by_ref.get(offer["ref"])))
        if by_gtin:
            for offer in adapter.find_by_gtins(sorted(by_gtin)):
                found.append((offer, by_gtin.get(offer["gtin"])))
    return found


def _safe_ref(target: str) -> tuple:
    try:
        return parse_ref(target)
    except Exception:
        return "", ""


def _bucket(offers_with_dates: list) -> dict:
    """Group what the user watches by shared category."""
    mapping = categories.mapping()
    buckets: dict = {}
    for offer, created_at in offers_with_dates:
        category = mapping.category_for(offer["store"], offer.get("category_path")) or UNCATEGORISED
        bucket = buckets.setdefault(category, {"refs": [], "groups": set(), "latest": None})
        if offer["ref"] not in bucket["refs"]:
            bucket["refs"].append(offer["ref"])
        bucket["groups"].add(_row_key({"group_id": offer.get("group_id"), "offers": [offer]}))
        if created_at and (bucket["latest"] is None or created_at > bucket["latest"]):
            bucket["latest"] = created_at
    return buckets


def rank_categories(buckets: dict, top_n: int = TOP_CATEGORIES) -> list:
    """The categories the user watches most, most recent first on a tie."""
    ranked = sorted(
        buckets.items(),
        key=lambda item: (len(item[1]["groups"]), item[1]["latest"] or ""),
        reverse=True,
    )
    return [name for name, _ in ranked[:top_n]]


def allocate(count: int, total: int) -> list:
    """Split ``total`` slots evenly; the first buckets take the remainder."""
    if count <= 0:
        return []
    base, extra = divmod(total, count)
    return [base + (1 if index < extra else 0) for index in range(count)]


# -- picks --------------------------------------------------------------------------

def _candidate_rows(category: str, refs: list, store_ids: list, slots: int, watched: set) -> list:
    """``(score, row)`` for one category bucket, best first."""
    vectors = semantic.vectors_for(refs)
    if not vectors:
        return []
    hits = semantic.nearest(
        semantic.mean_vector(list(vectors.values())),
        store_ids,
        max(int(slots * OVERSEARCH), slots + 1),
    )
    by_store: dict = {}
    scores: dict = {}
    for ref, score in hits:
        store_id, product_id = _safe_ref(ref)
        if store_id not in store_ids:
            continue
        by_store.setdefault(store_id, []).append(product_id)
        scores[ref] = score

    found = [offer
             for store_id, ids in by_store.items()
             for offer in queries.adapter_for(store_id).find_by_ids(ids)]
    # A vector carries its own store's category, so the shared one is applied here.
    if category != UNCATEGORISED:
        found = [o for o in found if categories.matches(o["store"], o.get("category_path"), category)]
    found = [o for o in found if _row_key({"group_id": o.get("group_id"), "offers": [o]}) not in watched]
    if not found:
        return []

    groups = queries._group_in_order(found)
    queries._fill_missing_stores(groups, store_ids)
    scored = []
    for group in groups:
        selected = [offer for offer in group if offer["store"] in store_ids]
        if not selected:
            continue
        row = queries.make_row(selected, store_ids)
        similarity = max((scores.get(offer["ref"], 0.0) for offer in selected), default=0.0)
        discount = max((offer.get("discount_ratio") or 0.0 for offer in selected), default=0.0)
        scored.append((SIMILARITY_WEIGHT * similarity + (1 - SIMILARITY_WEIGHT) * discount, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:slots]


def personal_rows(alerts: list, store_ids: list, limit: int) -> list:
    """Products similar to what the user watches, from every selected store.

    Returns an empty list when the user watches nothing, when none of it has a
    vector yet, or when the vector store is unavailable - the caller then falls
    back to the discount rows, which is a worse answer but always an answer.
    """
    if not alerts or not store_ids:
        return []
    try:
        buckets = _bucket(watched_offers(alerts, store_ids))
        if not buckets:
            return []
        watched = {group for bucket in buckets.values() for group in bucket["groups"]}
        chosen = rank_categories(buckets)
        picks = []
        seen = set()
        for category, slots in zip(chosen, allocate(len(chosen), limit)):
            if slots <= 0:
                continue
            for score, row in _candidate_rows(category, buckets[category]["refs"], store_ids, slots, watched):
                key = _row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                picks.append((score, row))
        picks.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in picks[:limit]]
    except semantic.SemanticUnavailable as exc:
        logger.warning(
            "Personal recommendations unavailable, answering with discounts: %s", exc,
            extra={"Action": "recommendations.semantic_unavailable", "Category": "search"},
        )
        return []


# -- the response -------------------------------------------------------------------

def rows(store_ids: list, limit: int, alerts: Optional[list] = None) -> dict:
    """Personal picks first, then the biggest discounts, as product rows."""
    results = personal_rows(alerts or [], store_ids, limit)[:limit]
    personalized = len(results)
    seen = {_row_key(row) for row in results}

    if len(results) < limit and store_ids:
        window = min(limit * 2, queries.MAX_WINDOW)
        for row in queries.browse(store_ids, 0, window, "discount", "desc")["results"]:
            if _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            results.append(row)
            if len(results) >= limit:
                break

    return {
        "type": "personalized" if personalized else "cold_start",
        "personalized_count": personalized,
        "results": results,
        "stores": store_ids,
    }
