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
        _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=10)
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

def get_cold_start_recommendations(products_collection, limit: int = 20) -> list[dict]:
    """Get globally discounted/deal products for anonymous/new users.

    Queries MongoDB for products with an active discount OR clubcard price
    in their latest price history entry, sorted by best deal percentage.
    """
    pipeline = [
        # Get the last price_history entry
        {"$addFields": {
            "latest_entry": {"$arrayElemAt": ["$price_history", -1]}
        }},
        # Filter: must have a normal price AND at least one deal (discount or clubcard)
        {"$match": {
            "latest_entry.normal.price": {"$ne": None},
            "$or": [
                {"latest_entry.discount.price": {"$ne": None}},
                {"latest_entry.clubcard.price": {"$ne": None}},
            ],
        }},
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


# ── Logged-In Recommendations ────────────────────────────────────────────────

def get_user_tracked_products(user_id: str) -> list[str]:
    """Get product IDs the user has alerts on (their tracked/liked items)."""
    try:
        alerts_db = _get_alerts_db()
        alerts_coll = alerts_db["alerts"]
        # Get distinct product IDs from user's alerts
        product_ids = alerts_coll.distinct(
            "productId",
            {"userId": user_id, "enabled": True}
        )
        return product_ids
    except Exception as e:
        logger.error(f"Failed to fetch user tracked products: {e}")
        return []


def get_product_vectors(products_collection, product_ids: list[str]) -> dict:
    """Fetch vectors for given product IDs from Qdrant.

    Returns: dict mapping product_id -> {"vector": [...], "category": "..."}
    """
    if not product_ids:
        return {}

    qdrant = _get_qdrant()
    results = {}

    # Convert product IDs to Qdrant point IDs
    point_ids = [_string_to_qdrant_id(pid) for pid in product_ids]

    try:
        points = qdrant.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=point_ids,
            with_vectors=True,
            with_payload=True,
        )
        for point in points:
            product_id = point.payload.get("product_id", "")
            results[product_id] = {
                "vector": point.vector,
                "category": point.payload.get("category", ""),
            }
    except Exception as e:
        logger.error(f"Failed to retrieve vectors from Qdrant: {e}")

    return results


def group_by_category(
    product_vectors: dict, max_groups: int = 5
) -> dict[str, list[list[float]]]:
    """Group product vectors by their deepest category.

    Returns the top N category groups (by count), each containing
    the list of vectors for products in that category.
    """
    groups: dict[str, list[list[float]]] = {}

    for product_id, data in product_vectors.items():
        category = data.get("category", "")
        if not category:
            continue
        if category not in groups:
            groups[category] = []
        groups[category].append(data["vector"])

    # Sort by group size (most tracked categories first) and take top N
    sorted_groups = dict(
        sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)[:max_groups]
    )

    return sorted_groups


def search_qdrant_by_category(
    mean_vector: list[float],
    category: str,
    limit: int = 50,
    exclude_ids: Optional[list[str]] = None,
) -> list[str]:
    """Search Qdrant for similar products within a specific category.

    CRITICAL: Uses a strict payload filter to prevent "Vector Bleed"
    across categories.

    Returns list of product_id strings.
    """
    qdrant = _get_qdrant()

    # Strict category filter — prevents vector bleed
    search_filter = Filter(
        must=[
            FieldCondition(
                key="category",
                match=MatchValue(value=category),
            )
        ]
    )

    try:
        results = qdrant.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=mean_vector,
            query_filter=search_filter,
            limit=limit,
            with_payload=True,
        )

        product_ids = []
        for hit in results:
            pid = hit.payload.get("product_id", "")
            if pid and (not exclude_ids or pid not in exclude_ids):
                product_ids.append(pid)

        return product_ids
    except Exception as e:
        logger.error(f"Qdrant search failed for category '{category}': {e}")
        return []


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


def sort_by_discount(products: list[dict]) -> list[dict]:
    """Sort products by active discount (items with discounts first).

    Business logic: push products with active discounts to the top,
    sorted by discount percentage. Non-discounted items follow.
    """
    def _discount_sort_key(product: dict) -> tuple:
        normal = product.get("last_scraped_price")
        discount = product.get("discount_price")
        clubcard = product.get("clubcard_price")

        # Calculate best available discount
        best_discount_pct = 0.0
        if isinstance(normal, (int, float)) and normal > 0:
            if isinstance(discount, (int, float)):
                best_discount_pct = max(best_discount_pct, (normal - discount) / normal)
            if isinstance(clubcard, (int, float)):
                best_discount_pct = max(best_discount_pct, (normal - clubcard) / normal)

        has_discount = best_discount_pct > 0
        # Sort: discounted first (has_discount=True sorts before False when negated)
        # Then by discount percentage descending
        return (not has_discount, -best_discount_pct)

    return sorted(products, key=_discount_sort_key)


# ── Main Recommendation Function ─────────────────────────────────────────────

def get_recommendations(
    products_collection,
    user_id: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Get personalized product recommendations.

    Args:
        products_collection: MongoDB products collection
        user_id: Authenticated user ID (None for cold start)
        limit: Max number of recommendations to return

    Returns:
        dict with keys: recommendations (list), type ("cold_start" | "personalized")
    """
    # ── Cold Start: No user or no tracked products ────────────────────────────
    if not user_id:
        recommendations = get_cold_start_recommendations(products_collection, limit=limit)
        return {
            "recommendations": recommendations,
            "type": "cold_start",
            "count": len(recommendations),
        }

    # Get user's tracked items
    tracked_ids = get_user_tracked_products(user_id)
    if not tracked_ids:
        # User is logged in but has no alerts — fall back to cold start
        recommendations = get_cold_start_recommendations(products_collection, limit=limit)
        return {
            "recommendations": recommendations,
            "type": "cold_start",
            "count": len(recommendations),
        }

    # ── Personalized: Semantic search based on tracked items ──────────────────
    try:
        # Get vectors for tracked products
        product_vectors = get_product_vectors(products_collection, tracked_ids)

        if not product_vectors:
            # Tracked products don't have vectors yet — cold start fallback
            logger.info(f"User {user_id}: no vectors for tracked products, falling back")
            recommendations = get_cold_start_recommendations(products_collection, limit=limit)
            return {
                "recommendations": recommendations,
                "type": "cold_start",
                "count": len(recommendations),
            }

        # Group by deepest category
        category_groups = group_by_category(product_vectors, max_groups=5)

        if not category_groups:
            recommendations = get_cold_start_recommendations(products_collection, limit=limit)
            return {
                "recommendations": recommendations,
                "type": "cold_start",
                "count": len(recommendations),
            }

        # Calculate mean vectors and search Qdrant per category
        all_candidate_ids: list[str] = []
        exclude_set = set(tracked_ids)  # Don't recommend items user already tracks

        for category, vectors in category_groups.items():
            mean_vec = compute_mean_vector(vectors)
            candidate_ids = search_qdrant_by_category(
                mean_vector=mean_vec,
                category=category,
                limit=50,
                exclude_ids=list(exclude_set),
            )
            all_candidate_ids.extend(candidate_ids)

        # Deduplicate while preserving order
        seen = set()
        unique_ids = []
        for pid in all_candidate_ids:
            if pid not in seen and pid not in exclude_set:
                seen.add(pid)
                unique_ids.append(pid)

        # Hydrate with full product data from MongoDB
        hydrated = hydrate_products(products_collection, unique_ids[:limit * 2])

        # Apply business sorting: active discounts first
        sorted_products = sort_by_discount(hydrated)

        # Trim to requested limit
        recommendations = sorted_products[:limit]

        return {
            "recommendations": recommendations,
            "type": "personalized",
            "count": len(recommendations),
            "categories_used": list(category_groups.keys()),
        }

    except Exception as e:
        logger.error(f"Personalized recommendation failed: {e}", exc_info=True)
        # Graceful degradation to cold start
        recommendations = get_cold_start_recommendations(products_collection, limit=limit)
        return {
            "recommendations": recommendations,
            "type": "cold_start",
            "count": len(recommendations),
        }
