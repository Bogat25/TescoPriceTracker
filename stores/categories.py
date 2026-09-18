"""One category vocabulary across stores.

Every store publishes its own category tree, so a store-neutral category filter
needs a single vocabulary. Tesco's is the canonical one: it is the larger
catalogue and the site has always browsed by it. Two levels are used
(super department > department), because deeper Tesco levels are far finer than
anything another store publishes.

Another store's paths are mapped onto it from the products the two stores
already share. A barcode links two listings, so every linked pair is one vote
for "this source path belongs to that canonical category". Votes are counted at
every prefix of the source path, and a path takes the deepest prefix that is
both well supported and largely unanimous; a path nothing agrees on stays
unmapped rather than being guessed, which is why the build reports coverage.

The mapping is derived data, rebuilt after a scrape into ``category_map``
alongside the canonical categories themselves. Readers cache it briefly and
fall back to "no categories" when the collection is unavailable, so a database
hiccup costs a filter rather than the catalogue.
"""

import logging
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from typing import Callable, Iterable, Optional

from pymongo import ReplaceOne
from pymongo import errors as mongo_errors

from mongo import database_manager as db


logger = logging.getLogger(__name__)

COLLECTION = "category_map"
CANONICAL_STORE = "tesco"
DEPTH = 2               # super department > department
MIN_SUPPORT = 3         # linked products behind a mapped path
MIN_CONFIDENCE = 0.6    # share of them that agree
DEFAULT_TTL_SECONDS = 300.0

_PATH_SEPARATOR = ">"
_NON_SLUG = re.compile(r"[^a-z0-9]+")


class UnknownCategory(LookupError):
    pass


# -- canonical identifiers ----------------------------------------------------------

def _slug(name: str) -> str:
    """Accent-free, URL-safe form of a category name ("Tejtermékek" -> "tejtermekek")."""
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return _NON_SLUG.sub("-", ascii_name).strip("-")


def canonical_names(category_path: Iterable) -> tuple:
    """The first ``DEPTH`` non-empty levels of a canonical-store path."""
    names = [str(part).strip() for part in category_path or () if part and str(part).strip()]
    return tuple(names[:DEPTH])


def canonical_id(category_path: Iterable) -> Optional[str]:
    """``"alapveto-elelmiszerek/tejtermekek"``, or None when the path is unusable.

    A path must reach the full depth: a product filed only under a super
    department cannot be told apart from the department of the same name.
    """
    names = canonical_names(category_path)
    if len(names) < DEPTH:
        return None
    parts = [_slug(name) for name in names]
    return "/".join(parts) if all(parts) else None


# -- building the mapping -----------------------------------------------------------

def build_mapping(pairs: Iterable, *, min_support: int = MIN_SUPPORT,
                  min_confidence: float = MIN_CONFIDENCE) -> list:
    """Map a store's category paths onto canonical categories.

    ``pairs`` is ``(source_path, canonical_id)`` for every product of the store,
    with None for products that no linked product places anywhere. Returns one
    entry per mapped path, deepest match first, with the evidence behind it.
    """
    votes = defaultdict(Counter)
    seen = set()
    for source_path, category in pairs:
        path = tuple(str(part).strip() for part in source_path or () if part and str(part).strip())
        if not path:
            continue
        seen.add(path)
        if not category:
            continue
        for depth in range(len(path), 0, -1):
            votes[path[:depth]][category] += 1

    entries = []
    for path in sorted(seen):
        for depth in range(len(path), 0, -1):
            counter = votes.get(path[:depth])
            if not counter:
                continue
            category, support = counter.most_common(1)[0]
            total = sum(counter.values())
            if support >= min_support and support / total >= min_confidence:
                entries.append({
                    "path": list(path),
                    "category": category,
                    "support": support,
                    "votes": total,
                    "confidence": round(support / total, 3),
                    "depth": depth,
                })
                break
    return entries


def _pairs_for_store(adapter, canonical_by_gtin: dict):
    """``(path, canonical_id)`` per product, plus how many products each path holds."""
    pairs = []
    path_counts = Counter()
    for gtin_norm, category_path in adapter.iter_categories():
        path = tuple(str(part).strip() for part in category_path or () if part and str(part).strip())
        if path:
            path_counts[path] += 1
        pairs.append((path, canonical_by_gtin.get(gtin_norm) if gtin_norm else None))
    return pairs, path_counts


def _coverage(entries: list, path_counts: Counter) -> dict:
    mapped_paths = {tuple(entry["path"]) for entry in entries}
    products = sum(path_counts.values())
    mapped_products = sum(count for path, count in path_counts.items() if path in mapped_paths)
    return {
        "paths": len(path_counts),
        "mapped_paths": len(mapped_paths & set(path_counts)),
        "products": products,
        "mapped_products": mapped_products,
        "product_coverage": round(mapped_products / products, 4) if products else 0.0,
    }


# -- storage ------------------------------------------------------------------------

def _collection():
    return db.get_database()[COLLECTION]


def ensure_indexes() -> None:
    _collection().create_index([("kind", 1), ("store", 1)], name="category_map_kind_store")


def _map_id(store_id: str, path) -> str:
    return f"{store_id}:{_PATH_SEPARATOR.join(path)}"


def rebuild(store_ids: Optional[list] = None, now: Optional[datetime] = None) -> dict:
    """Rebuild the canonical categories and every other store's mapping.

    Returns the build report: the canonical category count and, per store, how
    much of its catalogue the mapping covers.
    """
    from stores import queries
    from stores.registry import registry

    now = (now or datetime.now()).isoformat()
    store_ids = store_ids or [store.id for store in registry.all()]
    canonical_adapter = queries.adapter_for(CANONICAL_STORE)

    canonical_by_gtin = {}
    names_by_id = {}
    counts = defaultdict(Counter)
    for gtin_norm, category_path in canonical_adapter.iter_categories():
        category = canonical_id(category_path)
        if not category:
            continue
        names_by_id.setdefault(category, list(canonical_names(category_path)))
        counts[category][CANONICAL_STORE] += 1
        if gtin_norm:
            canonical_by_gtin[gtin_norm] = category

    documents = []
    report = {"categories": len(names_by_id), "stores": {}}
    for store_id in store_ids:
        if store_id == CANONICAL_STORE:
            continue
        pairs, path_counts = _pairs_for_store(queries.adapter_for(store_id), canonical_by_gtin)
        entries = build_mapping(pairs)
        for entry in entries:
            counts[entry["category"]][store_id] += path_counts.get(tuple(entry["path"]), 0)
            documents.append(ReplaceOne(
                {"_id": _map_id(store_id, entry["path"])},
                {"_id": _map_id(store_id, entry["path"]), "kind": "map", "store": store_id,
                 "built_at": now, **entry},
                upsert=True,
            ))
        report["stores"][store_id] = _coverage(entries, path_counts)

    for category, names in sorted(names_by_id.items()):
        documents.append(ReplaceOne(
            {"_id": f"category:{category}"},
            {"_id": f"category:{category}", "kind": "category", "store": CANONICAL_STORE,
             "category": category, "names": names, "counts": dict(counts[category]), "built_at": now},
            upsert=True,
        ))

    collection = _collection()
    if documents:
        collection.bulk_write(documents, ordered=False)
    collection.delete_many({"built_at": {"$ne": now}})
    _cache.invalidate()
    logger.info(
        "Category mapping rebuilt.",
        extra={"Action": "categories.rebuilt", "Category": "job", "Result": report},
    )
    return report


def rebuild_safely(store_ids: Optional[list] = None) -> bool:
    """Rebuild after a scrape. Never raises: a stale mapping beats a failed run."""
    try:
        rebuild(store_ids)
        return True
    except Exception:
        logger.exception(
            "Rebuilding the category mapping failed.",
            extra={"Action": "categories.rebuild_failed", "Category": "job"},
        )
        return False


# -- reading ------------------------------------------------------------------------

class Mapping:
    """A loaded mapping: which canonical category each store's paths belong to."""

    def __init__(self, categories: dict, paths_by_store: dict):
        self.categories = categories                  # id -> {"names": [...], "counts": {...}}
        self._paths_by_store = paths_by_store          # store -> {path tuple: category id}

    def category_for(self, store_id: str, category_path: Iterable) -> Optional[str]:
        if store_id == CANONICAL_STORE:
            return canonical_id(category_path)
        path = tuple(str(part).strip() for part in category_path or () if part and str(part).strip())
        return self._paths_by_store.get(store_id, {}).get(path)

    def paths_for(self, store_id: str, category: str) -> list:
        return sorted(path for path, mapped in self._paths_by_store.get(store_id, {}).items()
                      if mapped == category)

    def names_for(self, category: str) -> list:
        entry = self.categories.get(category)
        return list(entry["names"]) if entry else []

    def listing(self, store_ids: Optional[list] = None) -> list:
        """Canonical categories with their per-store product counts, for the API."""
        rows = []
        for category, entry in self.categories.items():
            counts = entry.get("counts") or {}
            if store_ids is not None:
                counts = {store_id: counts.get(store_id, 0) for store_id in store_ids}
                if not any(counts.values()):
                    continue
            rows.append({"id": category, "names": list(entry["names"]),
                         "name": entry["names"][-1] if entry["names"] else category,
                         "counts": counts, "products": sum(counts.values())})
        rows.sort(key=lambda row: (row["names"], row["id"]))
        return rows


EMPTY = Mapping({}, {})


class _MappingCache:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._value: Optional[Mapping] = None
        self._loaded_at = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._value = None

    def get(self) -> Mapping:
        with self._lock:
            now = self._clock()
            if self._value is None or now - self._loaded_at >= self._ttl:
                self._value = _load()
                self._loaded_at = now
            return self._value


def _load() -> Mapping:
    try:
        documents = list(_collection().find({}))
    except mongo_errors.PyMongoError:
        logger.warning(
            "Category mapping unavailable; category filters are off.",
            exc_info=True,
            extra={"Action": "categories.unavailable", "Category": "dependency"},
        )
        return EMPTY

    categories = {}
    paths_by_store: dict = defaultdict(dict)
    for document in documents:
        if document.get("kind") == "category":
            categories[document["category"]] = {"names": document.get("names") or [],
                                                "counts": document.get("counts") or {}}
        elif document.get("kind") == "map" and document.get("store"):
            paths_by_store[document["store"]][tuple(document.get("path") or ())] = document["category"]
    return Mapping(categories, dict(paths_by_store))


_cache = _MappingCache()


def mapping() -> Mapping:
    return _cache.get()


def invalidate() -> None:
    _cache.invalidate()


# -- filtering ----------------------------------------------------------------------

def resolve(category: Optional[str]) -> Optional[str]:
    """Validate a requested category, or None when no filter was asked for."""
    if category is None or not str(category).strip():
        return None
    category = str(category).strip().lower()
    if category not in mapping().categories:
        raise UnknownCategory(category)
    return category


def query_for(store_id: str, category: Optional[str]) -> Optional[dict]:
    """A Mongo fragment selecting one canonical category in one store's collection.

    Returns None when nothing is filtered, and a fragment that matches nothing
    when the store has no products in the category — the two are different
    answers and must not be confused.
    """
    if not category:
        return None
    current = mapping()
    if store_id == CANONICAL_STORE:
        names = current.names_for(category)
        if len(names) < DEPTH:
            return {"_id": {"$in": []}}
        return {"super_department_name": names[0], "department_name": names[1]}
    paths = current.paths_for(store_id, category)
    return {"category_path": {"$in": [list(path) for path in paths]}}


def matches(store_id: str, category_path: Iterable, category: Optional[str]) -> bool:
    """Whether one product is in the category, for results not fetched by query."""
    if not category:
        return True
    return mapping().category_for(store_id, category_path) == category
