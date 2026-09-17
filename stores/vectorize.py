"""Keep the Qdrant ``offers`` collection in step with every enabled store's catalogue.

Runs as its own container (``vectorizer``): a pass every
``VECTORIZE_INTERVAL_SECONDS``. A pass builds each product's embedding text,
compares its hash with ``embedding_state`` and embeds only new or changed
products, so a normal day costs seconds and the first pass fills the whole
collection. Products that left a catalogue lose their point.

    python -m stores.vectorize                # loop
    python -m stores.vectorize --once         # one pass, then exit
    python -m stores.vectorize --healthcheck  # container health check
"""

import argparse
import hashlib
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

import requests
from pymongo import UpdateOne

from mongo import database_manager as db
from stores import embedding_text, offers, semantic
from stores.auchan import repository as auchan_repository
from stores.registry import registry


logger = logging.getLogger(__name__)

STATE_COLLECTION = "embedding_state"
BATCH_SIZE = int(os.environ.get("VECTORIZE_BATCH_SIZE", "64"))
INTERVAL_SECONDS = int(os.environ.get("VECTORIZE_INTERVAL_SECONDS", "1800"))
HEARTBEAT_FILE = os.environ.get("VECTORIZE_HEARTBEAT_FILE", "/tmp/vectorizer-heartbeat")
MAX_HEARTBEAT_AGE_SECONDS = INTERVAL_SECONDS + 900


# -- sources: (ref, text, payload) per product ---------------------------------------

def _tesco_items() -> Iterator[tuple]:
    projection = {field: 1 for field in embedding_text.TESCO_FIELDS}
    projection.update(tpnc=1, gtin_norm=1)
    for doc in db.get_db().find({}, projection, batch_size=500):
        product_id = str(doc.get("tpnc") or doc["_id"])
        category = doc.get("shelf_name") or doc.get("aisle_name") or doc.get("department_name") or ""
        yield (f"tesco:{product_id}", embedding_text.tesco_text(doc),
               {"product_id": product_id, "name": doc.get("name"), "category": category,
                "gtin_norm": doc.get("gtin_norm"), "group_id": offers.group_id_for(doc.get("gtin_norm"))})


def _auchan_items() -> Iterator[tuple]:
    projection = {field: 1 for field in embedding_text.AUCHAN_FIELDS}
    projection.update(gtin_norm=1)
    for doc in auchan_repository.products().find({}, projection, batch_size=500):
        path = [c for c in doc.get("category_path") or [] if c]
        yield (f"auchan:{doc['_id']}", embedding_text.auchan_text(doc),
               {"product_id": str(doc["_id"]), "name": doc.get("name"), "category": path[-1] if path else "",
                "gtin_norm": doc.get("gtin_norm"), "group_id": offers.group_id_for(doc.get("gtin_norm"))})


SOURCES: dict = {"tesco": _tesco_items, "auchan": _auchan_items}


def state_collection():
    return db.get_database()[STATE_COLLECTION]


def text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def embedding_model() -> str:
    """Model identity reported by the embedding service; a new model re-embeds everything."""
    try:
        response = requests.get(f"{semantic.EMBEDDING_SERVICE_URL}/info", timeout=10)
        response.raise_for_status()
        info = response.json()
        return f"{info['model']}@{info['revision']}"
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise semantic.SemanticUnavailable(f"embedding service: {exc}") from exc


# -- one store --------------------------------------------------------------------

def sync_store(store_id: str, model: str, heartbeat: Callable[[], None] = lambda: None) -> dict:
    from qdrant_client.models import PointIdsList, PointStruct

    states = state_collection()
    known = {doc["_id"]: doc.get("hash") for doc in states.find({"store": store_id}, {"hash": 1})}
    counts = {"embedded": 0, "unchanged": 0, "no_text": 0, "removed": 0}
    seen: set = set()
    pending: list = []

    def flush():
        if not pending:
            return
        vectors = semantic.embed([text for _, text, _, _ in pending], "passage")
        points = [
            PointStruct(id=semantic.point_id(ref), vector=vector, payload=dict(payload, ref=ref, store=store_id))
            for (ref, _, payload, _), vector in zip(pending, vectors)
        ]
        try:
            semantic.client().upsert(semantic.COLLECTION, points=points)
        except Exception as exc:
            raise semantic.SemanticUnavailable(f"qdrant: {exc}") from exc
        now = datetime.now(timezone.utc)
        states.bulk_write([
            UpdateOne({"_id": ref}, {"$set": {"store": store_id, "hash": digest, "embedded_at": now}}, upsert=True)
            for ref, _, _, digest in pending
        ], ordered=False)
        counts["embedded"] += len(pending)
        pending.clear()
        heartbeat()

    for ref, text, payload in SOURCES[store_id]():
        seen.add(ref)
        if not text:
            counts["no_text"] += 1
            continue
        digest = text_hash(model, text)
        if known.get(ref) == digest:
            counts["unchanged"] += 1
            continue
        pending.append((ref, text, payload, digest))
        if len(pending) >= BATCH_SIZE:
            flush()
    flush()

    gone = [ref for ref in known if ref not in seen]
    if gone:
        try:
            semantic.client().delete(semantic.COLLECTION, points_selector=PointIdsList(points=[semantic.point_id(r) for r in gone]))
        except Exception as exc:
            raise semantic.SemanticUnavailable(f"qdrant: {exc}") from exc
        states.delete_many({"_id": {"$in": gone}})
        counts["removed"] = len(gone)
    return counts


def run_pass(heartbeat: Callable[[], None] = lambda: None) -> bool:
    started = time.monotonic()
    try:
        model = embedding_model()
        semantic.ensure_collection()
        for store in registry.enabled():
            if store.id not in SOURCES:
                continue
            store_started = time.monotonic()
            counts = sync_store(store.id, model, heartbeat)
            logger.info(
                "Vectors for %s: %s embedded, %s unchanged, %s without text, %s removed.",
                store.id, counts["embedded"], counts["unchanged"], counts["no_text"], counts["removed"],
                extra={"Action": "vectorize.store_synced", "Category": "job", "Store": store.id,
                       "EmbeddedCount": counts["embedded"], "UnchangedCount": counts["unchanged"],
                       "RemovedCount": counts["removed"], "DurationMs": int((time.monotonic() - store_started) * 1000)},
            )
    except Exception as exc:
        logger.error(
            "Vectorize pass failed; the next pass continues where this one stopped: %s", exc,
            exc_info=not isinstance(exc, semantic.SemanticUnavailable),
            extra={"Action": "vectorize.failed", "Category": "job"},
        )
        return False
    logger.info("Vectorize pass completed in %.0f s.", time.monotonic() - started,
                extra={"Action": "vectorize.completed", "Category": "job",
                       "DurationMs": int((time.monotonic() - started) * 1000)})
    return True


# -- container ----------------------------------------------------------------------

def touch_heartbeat() -> None:
    try:
        Path(HEARTBEAT_FILE).touch()
    except OSError:
        logger.warning("Could not update the vectorizer heartbeat file.", exc_info=True)


def is_alive(path: str = HEARTBEAT_FILE, now: Optional[float] = None) -> bool:
    try:
        age = (now or time.time()) - os.path.getmtime(path)
    except OSError:
        return False
    return age <= MAX_HEARTBEAT_AGE_SECONDS


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return 0 if is_alive() else 1

    from logging_setup import setup_logging

    setup_logging()
    touch_heartbeat()
    if args.once:
        return 0 if run_pass(touch_heartbeat) else 1
    while True:
        ok = run_pass(touch_heartbeat)
        touch_heartbeat()
        # A failed pass (usually the embedding service still starting) retries sooner.
        wait = INTERVAL_SECONDS if ok else min(300, INTERVAL_SECONDS)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(min(60, max(1, deadline - time.monotonic())))
            touch_heartbeat()


if __name__ == "__main__":
    sys.exit(main())
