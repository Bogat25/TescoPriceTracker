"""Vectors for store offers: embedding-service client and the Qdrant ``offers`` collection.

One point per offer. The point ID is derived from the offer ref
(``tesco:123``), so re-embedding a product overwrites its point. Payload
fields let searches filter by store and skip a product's own group.
"""

import logging
import os
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Optional

import requests

logger = logging.getLogger(__name__)

EMBEDDING_SERVICE_URL = os.environ.get("EMBEDDING_SERVICE_URL", "http://embedding-service:8080").rstrip("/")
EMBEDDING_TIMEOUT_SECONDS = float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", "10"))
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_OFFERS_COLLECTION", "offers")
VECTOR_SIZE = 384  # intfloat/multilingual-e5-small
# Cosine similarity below this is not treated as a semantic match. E5 scores
# sit in a narrow band (unrelated texts still score ~0.7); calibrated with
# scripts/search_eval.py, see docs/semantic-search.md.
MIN_SCORE = float(os.environ.get("SEMANTIC_MIN_SCORE", "0.82"))

_POINT_NAMESPACE = uuid.UUID("6f1c0e0a-3c1e-4d6b-9a57-7b0f6f3b2a10")
PAYLOAD_INDEXES = ("store", "ref", "group_id", "category")


class SemanticUnavailable(RuntimeError):
    """The embedding service or Qdrant could not answer."""


def point_id(ref: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, ref))


# -- embedding service ---------------------------------------------------------

def embed(texts: list, mode: str) -> list:
    """Vectors for ``texts``; ``mode`` is ``query`` or ``passage`` (the service adds the E5 prefix)."""
    if not texts:
        return []
    try:
        response = requests.post(
            f"{EMBEDDING_SERVICE_URL}/embed",
            json={"texts": texts, "mode": mode},
            timeout=EMBEDDING_TIMEOUT_SECONDS if mode == "query" else 120,
        )
        response.raise_for_status()
        vectors = response.json()["vectors"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise SemanticUnavailable(f"embedding service: {exc}") from exc
    if len(vectors) != len(texts):
        raise SemanticUnavailable("embedding service returned a different number of vectors")
    return vectors


class _QueryCache:
    """Recent query vectors; typing the same search again costs nothing."""

    def __init__(self, size: int = 512):
        self.size = size
        self.items: OrderedDict = OrderedDict()
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)


_query_cache = _QueryCache()


def embed_query(query: str) -> list:
    key = " ".join(query.lower().split())
    cached = _query_cache.get(key)
    if cached is None:
        cached = embed([key], "query")[0]
        _query_cache.put(key, cached)
    return cached


# -- Qdrant --------------------------------------------------------------------

_client = None


def client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        _client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY, https=False, timeout=10)
    return _client


def ensure_collection() -> None:
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    qdrant = client()
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(COLLECTION, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE))
        logger.info("Created Qdrant collection %s.", COLLECTION,
                    extra={"Action": "vectorize.collection_created", "Category": "job"})
    for field in PAYLOAD_INDEXES:
        qdrant.create_payload_index(COLLECTION, field_name=field, field_schema=PayloadSchemaType.KEYWORD)


def _filter(store_ids: list, exclude_group: Optional[str] = None, exclude_ref: Optional[str] = None):
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    must_not = []
    if exclude_group:
        must_not.append(FieldCondition(key="group_id", match=MatchValue(value=exclude_group)))
    if exclude_ref:
        must_not.append(FieldCondition(key="ref", match=MatchValue(value=exclude_ref)))
    return Filter(must=[FieldCondition(key="store", match=MatchAny(any=list(store_ids)))], must_not=must_not or None)


def nearest(vector: list, store_ids: list, limit: int, min_score: Optional[float] = None, **exclude) -> list:
    """``[(ref, score)]`` best first, only from ``store_ids``."""
    try:
        response = client().query_points(
            COLLECTION, query=vector, query_filter=_filter(store_ids, **exclude), limit=limit,
            with_payload=["ref"], score_threshold=min_score,
        )
    except Exception as exc:  # qdrant-client raises several transport types
        raise SemanticUnavailable(f"qdrant: {exc}") from exc
    return [(point.payload["ref"], point.score) for point in response.points if point.payload]


def vectors_for(refs: list) -> dict:
    """Stored vectors by ref (refs without a point are left out)."""
    if not refs:
        return {}
    try:
        points = client().retrieve(COLLECTION, ids=[point_id(ref) for ref in refs], with_vectors=True, with_payload=["ref"])
    except Exception as exc:
        raise SemanticUnavailable(f"qdrant: {exc}") from exc
    return {point.payload["ref"]: point.vector for point in points if point.payload and point.vector}


def mean_vector(vectors: list) -> list:
    size = len(vectors[0])
    return [sum(vector[i] for vector in vectors) / len(vectors) for i in range(size)]
