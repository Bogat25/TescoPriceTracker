"""Embedding service: turns Hungarian product and search texts into vectors.

Runs ``intfloat/multilingual-e5-small`` on the CPU. The model files are baked
into the image at build time, so the container needs no internet access and
starts the same way every time. E5 was trained with role prefixes, so callers
say whether a text is a search ``query`` or a product ``passage`` and the
service adds the prefix.

Internal only: the container sits on the stack's internal network with no
published port and no ingress. It holds no data, so it has no token either
(see docs/semantic-search.md, "Trust boundary").
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from logging_setup import correlation_middleware, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
MODEL_REVISION = os.environ.get("EMBEDDING_MODEL_REVISION", "unknown")
THREADS = int(os.environ.get("EMBEDDING_THREADS", "4"))
MAX_TEXTS = 128
MAX_CHARS = 4000
PREFIXES = {"query": "query: ", "passage": "passage: "}

_state: dict = {"model": None, "dimension": None}
# One encode at a time: torch already uses THREADS cores per call, and parallel
# calls would only fight over them. The lock is taken per chunk, not per request,
# so a search waits for one chunk (~100 ms) instead of a whole indexing batch.
_encode_lock = threading.Lock()
CHUNK = 16


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(THREADS)
    started = time.perf_counter()
    revision = None if MODEL_REVISION == "unknown" else MODEL_REVISION
    model = SentenceTransformer(MODEL_NAME, revision=revision, device="cpu")
    model.eval()
    loaded_ms = int((time.perf_counter() - started) * 1000)

    # Warm up and measure, so the logs show what this host can do.
    sample = ["passage: Milka alpesi tejcsokoládé 100 g. Márka: Milka. Kategória: Édesség, Csokoládé"] * 64
    model.encode(sample[:8], normalize_embeddings=True)
    started = time.perf_counter()
    model.encode(sample, batch_size=32, normalize_embeddings=True)
    per_second = len(sample) / (time.perf_counter() - started)
    logger.info(
        "Embedding model %s ready: loaded in %s ms, %.0f passages/s on %s threads.",
        MODEL_NAME, loaded_ms, per_second, THREADS,
        extra={"Action": "embedding.ready", "Category": "startup", "DurationMs": loaded_ms,
               "PassagesPerSecond": round(per_second), "Threads": THREADS},
    )
    return model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    model = load_model()
    _state["model"] = model
    _state["dimension"] = model.get_embedding_dimension()
    yield


app = FastAPI(title="Embedding service", version="1.0", lifespan=lifespan)
app.middleware("http")(correlation_middleware())


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
    mode: Literal["query", "passage"]


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dimension: int


def encode(texts: list, mode: str) -> list:
    model = _state["model"]
    if model is None:
        raise HTTPException(503, "model is loading")
    prefixed = [PREFIXES[mode] + " ".join(text.split())[:MAX_CHARS] for text in texts]
    vectors: list = []
    for start in range(0, len(prefixed), CHUNK):
        with _encode_lock:
            chunk = model.encode(prefixed[start:start + CHUNK], batch_size=CHUNK,
                                 normalize_embeddings=True, convert_to_numpy=True)
        vectors.extend(chunk.tolist())
    return vectors


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest):
    started = time.perf_counter()
    vectors = encode(request.texts, request.mode)
    if request.mode == "passage":
        logger.debug("Embedded %s passages in %.0f ms.", len(vectors), (time.perf_counter() - started) * 1000)
    return EmbedResponse(vectors=vectors, model=MODEL_NAME, dimension=len(vectors[0]))


@app.get("/info")
def info():
    return {"model": MODEL_NAME, "revision": MODEL_REVISION, "dimension": _state["dimension"], "threads": THREADS}


@app.get("/health")
def health():
    if _state["model"] is None:
        raise HTTPException(503, "model is loading")
    return {"status": "ok"}
