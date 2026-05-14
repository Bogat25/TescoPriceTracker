"""Internal Vector Sync API — Service B.

This microservice provides endpoints for the AI worker node (laptop) to:
1. GET un-vectorized products from MongoDB
2. POST completed vectors back, which are stored in Qdrant

Secured via API Token in the Authorization header.
Only accessible on the internal Docker network / admin_ingress.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    CollectionInfo,
)

import settings
from data_preparation import build_embedding_text

from logging_setup import setup_logging, correlation_middleware

setup_logging()
logger = logging.getLogger(__name__)

# ── Database clients ──────────────────────────────────────────────────────────
_mongo_client: Optional[MongoClient] = None
_qdrant_client: Optional[QdrantClient] = None


def get_mongo_collection():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(settings.MONGO_URI)
    db = _mongo_client[settings.MONGO_DB_NAME]
    return db[settings.MONGO_COLLECTION]


def get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY,
        )
    return _qdrant_client


def _ensure_qdrant_collection():
    """Create the Qdrant collection if it doesn't exist."""
    client = get_qdrant()
    collections = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION not in collections:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=settings.VECTOR_DIMENSION,
                distance=Distance.COSINE,
            ),
        )
        logger.info(f"Created Qdrant collection: {settings.QDRANT_COLLECTION}")
    else:
        logger.info(f"Qdrant collection '{settings.QDRANT_COLLECTION}' already exists.")


# ── Auth dependency ───────────────────────────────────────────────────────────

async def verify_api_token(authorization: str = Header(...)):
    """Validate the Bearer token against the configured API token."""
    if not settings.VECTOR_SYNC_API_TOKEN:
        raise HTTPException(status_code=500, detail="Server misconfigured: no API token set")
    expected = f"Bearer {settings.VECTOR_SYNC_API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_qdrant_collection()
    logger.info("Recommendation Vector Sync API started.")
    yield
    if _mongo_client:
        _mongo_client.close()
    if _qdrant_client:
        _qdrant_client.close()
    logger.info("Recommendation Vector Sync API shut down.")


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Recommendation Vector Sync API",
    version="1.0",
    lifespan=lifespan,
)
app.middleware("http")(correlation_middleware())


# ── Models ────────────────────────────────────────────────────────────────────

class ProductForVectorization(BaseModel):
    """Product data prepared for the worker node."""
    mongo_id: str
    category: Optional[str] = None
    embedding_text: str


class VectorPayloadItem(BaseModel):
    """A single vector result from the worker node."""
    mongo_id: str
    category: Optional[str] = None
    vector: list[float] = Field(..., min_length=384, max_length=384)


class VectorSyncRequest(BaseModel):
    """Batch of vectors from the worker node."""
    vectors: list[VectorPayloadItem]


class SyncResponse(BaseModel):
    """Response for the vector sync endpoint."""
    stored: int
    errors: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "recommendation-vector-sync"}


@app.get(
    "/api/internal/products/sync",
    response_model=list[ProductForVectorization],
    dependencies=[Depends(verify_api_token)],
)
def get_products_for_vectorization(
    limit: int = Query(default=100, ge=1, le=500),
):
    """Fetch products needing vectorization.

    Returns products where:
    - `needs_revector` is True, OR
    - `vector_embedding` field does not exist (new products)
    """
    coll = get_mongo_collection()

    query = {
        "$or": [
            {"needs_revector": True},
            {"vector_embedding": {"$exists": False}},
        ]
    }

    # Only fetch fields needed for embedding text construction
    projection = {
        "_id": 1,
        "tpnc": 1,
        "name": 1,
        "brand_name": 1,
        "sub_brand": 1,
        "super_department_name": 1,
        "department_name": 1,
        "aisle_name": 1,
        "shelf_name": 1,
        "short_description": 1,
        "marketing": 1,
        "product_marketing": 1,
        "features": 1,
        "nutritional_claims": 1,
        "ingredients": 1,
    }

    cursor = coll.find(query, projection).limit(limit)
    results = []

    for doc in cursor:
        mongo_id = str(doc.get("tpnc") or doc.get("_id"))
        category = doc.get("shelf_name") or doc.get("aisle_name") or doc.get("department_name")

        embedding_text = build_embedding_text(doc)
        if not embedding_text:
            # Mark as processed to avoid re-fetching products with no useful text
            coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"needs_revector": False, "vector_embedding": "skipped"}},
            )
            continue

        results.append(ProductForVectorization(
            mongo_id=mongo_id,
            category=category,
            embedding_text=embedding_text,
        ))

    logger.info(f"Returning {len(results)} products for vectorization")
    return results


@app.post(
    "/api/internal/vectors/sync",
    response_model=SyncResponse,
    dependencies=[Depends(verify_api_token)],
)
def sync_vectors(payload: VectorSyncRequest):
    """Accept completed vectors from the worker node.

    For each vector:
    1. Upsert into Qdrant with product_id and category as payload metadata
    2. Update MongoDB: set needs_revector=False, store vector reference
    """
    coll = get_mongo_collection()
    qdrant = get_qdrant()

    stored = 0
    errors = 0

    # Process in batches for Qdrant efficiency
    points = []
    mongo_updates = []

    for item in payload.vectors:
        try:
            # Use a deterministic numeric ID for Qdrant from the mongo_id string
            point_id = _string_to_qdrant_id(item.mongo_id)

            point = PointStruct(
                id=point_id,
                vector=item.vector,
                payload={
                    "product_id": item.mongo_id,
                    "category": item.category or "",
                },
            )
            points.append(point)
            mongo_updates.append(item.mongo_id)
        except Exception as e:
            logger.error(f"Error preparing vector for {item.mongo_id}: {e}")
            errors += 1

    # Batch upsert to Qdrant
    if points:
        try:
            qdrant.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
            )
            stored = len(points)
            logger.info(f"Upserted {stored} vectors to Qdrant")
        except Exception as e:
            logger.error(f"Qdrant batch upsert failed: {e}")
            errors += len(points)
            stored = 0
            mongo_updates = []

    # Update MongoDB flags
    for mongo_id in mongo_updates:
        try:
            coll.update_one(
                {"_id": mongo_id},
                {"$set": {"needs_revector": False, "vector_embedding": True}},
            )
        except Exception as e:
            logger.warning(f"Failed to update MongoDB flag for {mongo_id}: {e}")
            # Try with tpnc field match as fallback
            try:
                coll.update_one(
                    {"tpnc": mongo_id},
                    {"$set": {"needs_revector": False, "vector_embedding": True}},
                )
            except Exception:
                pass

    return SyncResponse(stored=stored, errors=errors)


def _string_to_qdrant_id(s: str) -> int:
    """Convert a string ID to a deterministic positive integer for Qdrant point ID.

    Uses a hash to guarantee consistent mapping between mongo_id and Qdrant point ID.
    """
    import hashlib
    h = hashlib.sha256(s.encode()).hexdigest()
    # Use first 15 hex chars to stay within safe int64 range
    return int(h[:15], 16)
