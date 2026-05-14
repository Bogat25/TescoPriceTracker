"""Recommendation engine for the backend API (Service A).

Implements the hybrid-search algorithm:
- Cold Start: Returns globally discounted products from MongoDB
- Logged-In: Semantic vector search via Qdrant + business logic sorting
"""

import hashlib
import logging
import os
from typing import Optional

from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, SearchRequest

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "products")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "tesco_tracker")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "products")
MONGO_ALERTS_DB_NAME = os.environ.get("MONGO_ALERTS_DB_NAME", "tesco_alerts")

# ── Clients ───────────────────────────────────────────────────────────────────

_qdrant_client: Optional[QdrantClient] = None
_alerts_mongo_client: Optional[MongoClient] = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            api_key=QDRANT_API_KEY,
            https=False,
            timeout=10,
        )
    return _qdrant_client


def _get_alerts_db():
    """Get the alerts database (separate from products db)."""
    global _alerts_mongo_client
    if _alerts_mongo_client is None:
        _alerts_mongo_client = MongoClient(MONGO_URI)
    return _alerts_mongo_client[MONGO_ALERTS_DB_NAME]


def _string_to_qdrant_id(s: str) -> int:
    """Must match the same function in Service B for consistency."""
    h = hashlib.sha256(s.encode()).hexdigest()
    return int(h[:15], 16)


# ── Vector Mathematics ────────────────────────────────────────────────────────

def compute_mean_vector(vectors: list[list[float]]) -> list[float]:
    """Calculate the element-wise mean of a list of vectors.

    Args:
        vectors: List of N-dimensional vectors (all same length)

    Returns:
        Mean vector of same dimensionality

    Raises:
        ValueError: If vectors list is empty or dimensions mismatch
    """
    if not vectors:
        raise ValueError("Cannot compute mean of empty vector list")

    dim = len(vectors[0])
    if dim == 0:
        raise ValueError("Vectors must have non-zero dimension")

    n = len(vectors)
    mean = [0.0] * dim

    for vec in vectors:
        if len(vec) != dim:
            raise ValueError(f"Dimension mismatch: expected {dim}, got {len(vec)}")
        for i in range(dim):
            mean[i] += vec[i]

    for i in range(dim):
        mean[i] /= n

    return mean


# ── Cold Start Recommendations ────────────────────────────────────────────────

def get_cold_start_recommendations(
    products_collection,
    limit: int = 20,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Get discounted/deal products sorted by best discount percentage.

    Args:
        exclude_ids: Product tpnc/ids to omit (tracked by user or already shown).
    """
    match_stage: dict = {
        "latest_entry.normal.price": {"$ne": None},
        "$or": [
            {"latest_entry.discount.price": {"$ne": None}},
            {"latest_entry.clubcard.price": {"$ne": None}},
        ],
    }
    if exclude_ids:
        match_stage["tpnc"] = {"$nin": exclude_ids}

    pipeline = [
        # Get the last price_history entry
        {"$addFields": {
            "latest_entry": {"$arrayElemAt": ["$price_history", -1]}
        }},
        # Filter: must have a normal price AND at least one deal (discount or clubcard)
        {"$match": match_stage},
        # Best deal price = minimum of discount/clubcard prices (ignoring nulls)
        {"$addFields": {
            "best_deal_price": {
                "$min": [
                    "$latest_entry.discount.price",
                    "$latest_entry.clubcard.price",
                ]
            }
        }},
        # Calculate deal percentage against normal price
        {"$addFields": {
            "discount_pct": {
                "$multiply": [
                    {"$divide": [
                        {"$subtract": [
                            "$latest_entry.normal.price",
                            "$best_deal_price"
                        ]},
                        "$latest_entry.normal.price"
                    ]},
                    100
                ]
            }
        }},
        # Sort by biggest discount
        {"$sort": {"discount_pct": -1}},
        # Limit results
        {"$limit": limit},
        # Project fields needed by frontend
        {"$project": {
            "_id": 0,
            "tpnc": {"$ifNull": ["$tpnc", {"$toString": "$_id"}]},
            "name": 1,
            "default_image_url": 1,
            "unit_of_measure": 1,
            "pack_size_value": 1,
            "pack_size_unit": 1,
            "brand_name": 1,
            "super_department_name": 1,
            "department_name": 1,
            "last_scraped_price": "$latest_entry.normal.price",
            "discount_price": "$latest_entry.discount.price",
            "discount_desc": "$latest_entry.discount.promo_desc",
            "clubcard_price": "$latest_entry.clubcard.price",
            "clubcard_desc": "$latest_entry.clubcard.promo_desc",
            "unit_price": "$latest_entry.normal.unit_price",
            "unit_measure": "$latest_entry.normal.unit_measure",
            "discount_pct": 1,
        }},
    ]

    try:
        results = list(products_collection.aggregate(pipeline))
        logger.info(f"Cold start: returning {len(results)} deal products")
        return results
    except Exception as e:
        logger.error(f"Cold start query failed: {e}")
        return []


# ── Alert & Category Helpers ──────────────────────────────────────────────────

def get_user_alert_details(user_id: str) -> list[dict]:
    """Return [{productId, createdAt}] for all enabled alerts of user_id."""
    try:
        alerts_coll = _get_alerts_db()["alerts"]
        docs = list(alerts_coll.find(
            {"userId": user_id, "enabled": True},
            {"productId": 1, "createdAt": 1, "_id": 0},
        ))
        return docs
    except Exception as e:
        logger.error(f"Failed to fetch alert details for {user_id}: {e}")
        return []


def resolve_product_categories(product_ids: list[str]) -> dict[str, str]:
    """Batch-retrieve Qdrant payloads → {product_id: deepest_category_string}."""
    if not product_ids:
        return {}
    qdrant = _get_qdrant()
    point_ids = [_string_to_qdrant_id(pid) for pid in product_ids]
    try:
        points = qdrant.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=point_ids,
            with_vectors=False,
            with_payload=True,
        )
        return {
            p.payload.get("product_id", ""): p.payload.get("category", "")
            for p in points
            if p.payload.get("product_id") and p.payload.get("category")
        }
    except Exception as e:
        logger.error(f"Failed to resolve product categories from Qdrant: {e}")
        return {}


def rank_top_categories(
    alert_details: list[dict],
    category_map: dict[str, str],
    top_n: int = 5,
) -> list[tuple[str, list[str]]]:
    """Group alerted products by category and return the top N.

    Primary sort:   number of alerted products in the category (DESC)
    Secondary sort: most recent alert createdAt in the category (DESC)

    Returns list of (category, [distinct_product_ids_in_category]).
    """
    groups: dict[str, dict] = {}
    for alert in alert_details:
        pid = alert.get("productId", "")
        cat = category_map.get(pid, "")
        if not cat:
            continue
        if cat not in groups:
            groups[cat] = {"product_ids": [], "latest": None}
        if pid not in groups[cat]["product_ids"]:
            groups[cat]["product_ids"].append(pid)
        created_at = alert.get("createdAt")
        if created_at and (
            groups[cat]["latest"] is None or created_at > groups[cat]["latest"]
        ):
            groups[cat]["latest"] = created_at

    ranked = sorted(
        groups.items(),
        key=lambda kv: (len(kv[1]["product_ids"]), kv[1]["latest"] or 0),
        reverse=True,
    )
    return [(cat, data["product_ids"]) for cat, data in ranked[:top_n]]


def allocate_slots(n_categories: int, total: int = 100) -> list[int]:
    """Distribute `total` slots evenly; first (total % n) categories get +1.

    Examples:
      allocate_slots(3, 100) → [34, 33, 33]
      allocate_slots(5, 100) → [20, 20, 20, 20, 20]
      allocate_slots(1, 100) → [100]
    """
    if n_categories <= 0:
        return []
    base = total // n_categories
    extra = total % n_categories
    return [base + (1 if i < extra else 0) for i in range(n_categories)]


def search_category_bucket(
    category: str,
    alerted_product_ids: list[str],
    slot_size: int,
    exclude_ids: set[str],
) -> list[dict]:
    """Search Qdrant for products similar to alerted_product_ids within category.

    Oversearches by 2.5× so the business-logic scoring step has enough
    candidates to pick from after deduplication and filtering.

    Returns [{"product_id": str, "score": float (cosine similarity)}, ...]
    """
    import math

    qdrant = _get_qdrant()

    # Retrieve vectors for the user's alerted products in this category
    point_ids = [_string_to_qdrant_id(pid) for pid in alerted_product_ids]
    try:
        points = qdrant.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=point_ids,
            with_vectors=True,
            with_payload=False,
        )
    except Exception as e:
        logger.error(f"Failed to retrieve vectors for category '{category}': {e}")
        return []

    vectors = [p.vector for p in points if p.vector is not None]
    if not vectors:
        return []

    mean_vec = compute_mean_vector(vectors)

    # 2.5× oversearch so scoring/dedup has room
    search_limit = math.ceil(slot_size * 2.5)

    search_filter = Filter(
        must=[FieldCondition(key="category", match=MatchValue(value=category))]
    )
    try:
        hits = qdrant.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=mean_vec,
            query_filter=search_filter,
            limit=search_limit,
            with_payload=True,
        )
    except Exception as e:
        logger.error(f"Qdrant search failed for category '{category}': {e}")
        return []

    results = []
    for hit in hits:
        pid = hit.payload.get("product_id", "")
        if pid and pid not in exclude_ids:
            results.append({"product_id": pid, "score": hit.score})
    return results


def hydrate_products(products_collection, product_ids: list[str]) -> list[dict]:
    """Fetch full product details from MongoDB for a list of product IDs.

    Returns product documents cleaned for frontend consumption.
    """
    if not product_ids:
        return []

    # Query by both _id and tpnc to handle different ID formats
    docs = list(products_collection.find({
        "$or": [
            {"_id": {"$in": product_ids}},
            {"tpnc": {"$in": product_ids}},
        ]
    }))

    results = []
    for doc in docs:
        tpnc = str(doc.get("tpnc") or doc.get("_id", ""))
        # Extract latest prices
        price_info = _extract_latest_prices(doc)

        results.append({
            "tpnc": tpnc,
            "name": doc.get("name"),
            "default_image_url": doc.get("default_image_url"),
            "unit_of_measure": doc.get("unit_of_measure"),
            "pack_size_value": doc.get("pack_size_value"),
            "pack_size_unit": doc.get("pack_size_unit"),
            "brand_name": doc.get("brand_name"),
            "super_department_name": doc.get("super_department_name"),
            "department_name": doc.get("department_name"),
            **price_info,
        })

    return results


def _extract_latest_prices(doc: dict) -> dict:
    """Extract current prices from the latest price_history entry."""
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


def _compute_discount_fraction(product: dict) -> float:
    """Return the best available discount as a 0.0–1.0 fraction."""
    normal = product.get("last_scraped_price")
    if not isinstance(normal, (int, float)) or normal <= 0:
        return 0.0
    discount = product.get("discount_price")
    clubcard = product.get("clubcard_price")
    best_deal: Optional[float] = None
    if isinstance(discount, (int, float)):
        best_deal = discount
    if isinstance(clubcard, (int, float)):
        best_deal = clubcard if best_deal is None else min(best_deal, clubcard)
    if best_deal is None or best_deal >= normal:
        return 0.0
    return (normal - best_deal) / normal


def score_and_rank_bucket(
    candidates: list[dict],
    hydrated_map: dict[str, dict],
    slot_size: int,
) -> list[tuple[float, dict]]:
    """Score each candidate and return the top slot_size (score, product) pairs.

    Combined score = 0.5 × vector_similarity  (Qdrant cosine score, 0–1)
                   + 0.5 × discount_fraction  (best deal / normal price, 0–1)

    Returns scored tuples so the caller can re-sort globally across buckets.

    candidates: [{"product_id": str, "score": float}]
    hydrated_map: {tpnc: product_dict}
    """
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        product = hydrated_map.get(c["product_id"])
        if not product:
            continue
        combined = 0.5 * c["score"] + 0.5 * _compute_discount_fraction(product)
        scored.append((combined, product))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:slot_size]


# ── Main Recommendation Function ─────────────────────────────────────────────

def get_recommendations(
    products_collection,
    user_id: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """Get personalized product recommendations.

    Algorithm for authenticated users with alerts:
      1. Fetch all enabled alerts with timestamps from the alerts DB.
      2. Resolve each alerted product's deepest category via Qdrant payload
         (batch retrieve, no vectors needed here).
      3. Rank the top-5 categories: primary = alert count DESC,
         tie-breaker = most recent alert createdAt DESC.
      4. Distribute `limit` slots evenly across categories; first
         (limit % n_cats) categories receive one extra slot.
         e.g. 3 cats, 100 slots → [34, 33, 33].
      5. Per category: compute mean vector of the user's alerted products
         in that category, then search Qdrant with a strict category filter
         at 2.5× the slot size (oversearch). Exclude alerted products.
      6. Batch-hydrate all candidates from MongoDB. Score each by
         (0.5 × cosine similarity + 0.5 × discount fraction), rank DESC,
         trim to slot size. Deduplicate globally across buckets.
      7. Append cold-start filler (top global discounts) for any remaining
         slots if personalized results don't fill `limit`.

    Users with no alerts, or when Qdrant is unavailable, receive a pure
    cold-start response (globally best-discounted products).

    Returns:
        dict with: recommendations, type, personalized_count, count
    """
    # ── No user → cold start ──────────────────────────────────────────────────
    if not user_id:
        logger.info("recommendations: no user_id → cold start")
        recs = get_cold_start_recommendations(products_collection, limit=limit)
        return {"recommendations": recs, "type": "cold_start",
                "personalized_count": 0, "count": len(recs)}

    try:
        # Step 1 — alert details
        logger.info("recommendations: user_id=%r fetching alerts", user_id)
        alert_details = get_user_alert_details(user_id)
        logger.info("recommendations: user_id=%r found %d alerts", user_id, len(alert_details))
        if not alert_details:
            recs = get_cold_start_recommendations(products_collection, limit=limit)
            return {"recommendations": recs, "type": "cold_start",
                    "personalized_count": 0, "count": len(recs)}

        alerted_ids: list[str] = list({a["productId"] for a in alert_details})

        # Step 2 — resolve deepest category per product from Qdrant payload
        category_map = resolve_product_categories(alerted_ids)
        logger.info("recommendations: user_id=%r category_map=%r", user_id, category_map)
        if not category_map:
            logger.info(f"User {user_id}: no Qdrant vectors found, cold start fallback")
            recs = get_cold_start_recommendations(products_collection, limit=limit)
            return {"recommendations": recs, "type": "cold_start",
                    "personalized_count": 0, "count": len(recs)}

        # Step 3 — rank top-5 categories
        top_categories = rank_top_categories(alert_details, category_map, top_n=5)
        if not top_categories:
            recs = get_cold_start_recommendations(products_collection, limit=limit)
            return {"recommendations": recs, "type": "cold_start",
                    "personalized_count": 0, "count": len(recs)}

        # Step 4 — equal slot allocation
        n = len(top_categories)
        slots = allocate_slots(n, total=limit)
        logger.info(
            f"User {user_id}: {n} categories {[c for c, _ in top_categories]}, "
            f"slots {slots}"
        )

        # Step 5 — per-category Qdrant oversearch (excludes alerted items)
        exclude_ids: set[str] = set(alerted_ids)
        per_category_candidates: list[list[dict]] = []
        all_candidate_ids: list[str] = []

        for (category, cat_product_ids), slot_size in zip(top_categories, slots):
            candidates = search_category_bucket(
                category=category,
                alerted_product_ids=cat_product_ids,
                slot_size=slot_size,
                exclude_ids=exclude_ids,
            )
            per_category_candidates.append(candidates)
            for c in candidates:
                all_candidate_ids.append(c["product_id"])

        # Step 6 — batch hydrate once, score + rank per bucket, global dedup
        unique_ids = list(dict.fromkeys(all_candidate_ids))
        hydrated_list = hydrate_products(products_collection, unique_ids)
        hydrated_map: dict[str, dict] = {p["tpnc"]: p for p in hydrated_list}

        shown: set[str] = set(alerted_ids)
        all_scored: list[tuple[float, dict]] = []

        for candidates, slot_size in zip(per_category_candidates, slots):
            fresh = [c for c in candidates if c["product_id"] not in shown]
            # score_and_rank_bucket selects the best slot_size from this category
            # (diversity guardrail) but returns scores so we can sort globally
            ranked = score_and_rank_bucket(fresh, hydrated_map, slot_size)
            for score, p in ranked:
                if p["tpnc"] not in shown:
                    shown.add(p["tpnc"])
                    all_scored.append((score, p))

        # Global re-sort: best combined score wins regardless of which category it came from
        all_scored.sort(key=lambda x: x[0], reverse=True)
        personalized = [p for _, p in all_scored]

        logger.info(f"User {user_id}: {len(personalized)} personalized results")

        # Step 7 — cold-start filler for any remaining slots
        remaining = limit - len(personalized)
        filler: list[dict] = []
        if remaining > 0:
            filler = get_cold_start_recommendations(
                products_collection,
                limit=remaining,
                exclude_ids=list(shown),
            )
            logger.info(f"User {user_id}: {len(filler)} cold-start filler items")

        recommendations = personalized + filler
        rec_type = "personalized" if personalized else "cold_start"

        return {
            "recommendations": recommendations,
            "type": rec_type,
            "personalized_count": len(personalized),
            "count": len(recommendations),
        }

    except Exception as e:
        logger.error(f"Personalized recommendation failed: {e}", exc_info=True)
        recs = get_cold_start_recommendations(products_collection, limit=limit)
        return {"recommendations": recs, "type": "cold_start",
                "personalized_count": 0, "count": len(recs)}
