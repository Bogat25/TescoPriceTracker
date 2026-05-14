"""Vector visualization service.

Pulls product vectors from Qdrant, projects them to 2D with UMAP, joins
MongoDB for human-readable names, and serves a static HTML page that
renders the result with Plotly.

Computes on every page load — slow but always fresh. Only reachable on
the admin tailnet via nginx (tesco-vector-viz.internal).
"""

import logging
import os
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from pymongo import MongoClient
from qdrant_client import QdrantClient
from umap import UMAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "products")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "tesco_tracker")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "products")

app = FastAPI(title="Tesco Vector Visualization")

_qdrant: QdrantClient | None = None
_mongo: MongoClient | None = None


def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            api_key=QDRANT_API_KEY,
            https=False,
            timeout=30,
        )
    return _qdrant


def get_mongo_collection():
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(MONGO_URI)
    return _mongo[MONGO_DB_NAME][MONGO_COLLECTION]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/projection")
def projection(limit: int = Query(default=3000, ge=100, le=10000)):
    """Pull `limit` vectors, run UMAP, join MongoDB for names, return points."""
    qdrant = get_qdrant()
    logger.info(f"Scrolling {limit} points from Qdrant")

    points, _ = qdrant.scroll(
        collection_name=QDRANT_COLLECTION,
        limit=limit,
        with_vectors=True,
        with_payload=True,
    )
    if not points:
        return JSONResponse({"error": "no vectors in Qdrant collection"}, status_code=503)

    vectors = np.array([p.vector for p in points], dtype=np.float32)
    payloads = [p.payload or {} for p in points]
    product_ids = [pl.get("product_id", "") for pl in payloads]
    categories = [pl.get("category", "") for pl in payloads]

    logger.info(f"Running UMAP on {len(vectors)} vectors")
    reducer = UMAP(
        n_neighbors=min(80, len(vectors) - 1),
        min_dist=0.4,
        spread=2.0,
        n_components=2,
        metric="cosine",
        random_state=42,
    )
    coords = reducer.fit_transform(vectors)

    # Color by 2D position — HSV hue from angle, saturation from distance to centre
    cx, cy = coords[:, 0].mean(), coords[:, 1].mean()
    dx = coords[:, 0] - cx
    dy = coords[:, 1] - cy
    angles = np.arctan2(dy, dx)
    hues = (angles + np.pi) / (2 * np.pi)  # 0..1
    radii = np.hypot(dx, dy)
    rmax = radii.max() or 1.0
    sats = 0.4 + 0.6 * (radii / rmax)  # 0.4..1.0

    def hsv_to_hex(h: float, s: float, v: float = 0.95) -> str:
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    colors = [hsv_to_hex(h, s) for h, s in zip(hues, sats)]

    # Join MongoDB for human-readable names
    logger.info("Joining MongoDB for product names")
    coll = get_mongo_collection()
    name_map: dict[str, str] = {}
    cursor = coll.find(
        {"$or": [{"_id": {"$in": product_ids}}, {"tpnc": {"$in": product_ids}}]},
        {"_id": 1, "tpnc": 1, "name": 1, "brand_name": 1},
    )
    for doc in cursor:
        key = str(doc.get("tpnc") or doc.get("_id"))
        nm = doc.get("name", "")
        br = doc.get("brand_name", "")
        name_map[key] = f"{br} — {nm}" if br else nm

    items = [
        {
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "color": colors[i],
            "category": categories[i],
            "name": name_map.get(product_ids[i], product_ids[i]),
        }
        for i in range(len(coords))
    ]
    return {"points": items, "count": len(items)}


# ── Static HTML ───────────────────────────────────────────────────────────────

STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
