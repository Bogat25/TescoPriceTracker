"""Configuration for the recommendation vector sync API."""

import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "tesco_tracker")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "products")

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "products")

VECTOR_SYNC_API_TOKEN = os.environ.get("VECTOR_SYNC_API_TOKEN", "")
VECTOR_DIMENSION = 384  # intfloat/multilingual-e5-small output dimension
