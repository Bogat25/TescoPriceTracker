"""Store registry: which stores exist and which parts of them are switched on.

The registry lives in the ``stores`` Mongo collection so a store can be hidden
or its scraping stopped without a redeploy (see ``python -m stores.admin``).
Every process caches it briefly; reads fall back to the defaults when MongoDB
is unavailable, so a database hiccup never hides every store.
"""

import logging
import threading
import time
from dataclasses import asdict, dataclass, replace
from typing import Callable, Optional

from pymongo import errors as mongo_errors

from stores.ids import STORE_ID_PATTERN


logger = logging.getLogger(__name__)

FLAG_FIELDS = ("enabled", "scrape_enabled", "loyalty_enabled")
DEFAULT_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class StoreConfig:
    id: str
    name: str
    enabled: bool          # visible to users: search, products, alerts, stats
    scrape_enabled: bool   # scheduler collects prices
    loyalty_enabled: bool  # loyalty-price reader runs
    order: int             # display and tie-break order
    website: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "order": self.order, "website": self.website}


DEFAULT_STORES = (
    StoreConfig("tesco", "Tesco", True, True, False, 10, "https://bevasarlas.tesco.hu"),
    StoreConfig("auchan", "Auchan", True, True, False, 20, "https://auchan.hu"),
)


class UnknownStore(LookupError):
    pass


class DisabledStore(LookupError):
    pass


class StoreRegistry:

    def __init__(
        self,
        collection_factory: Callable,
        defaults=DEFAULT_STORES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._collection_factory = collection_factory
        self._defaults = {store.id: store for store in defaults}
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: Optional[list[StoreConfig]] = None
        self._loaded_at = 0.0

    # -- persistence --------------------------------------------------------

    def seed(self) -> None:
        """Insert missing stores with their defaults; never overwrite toggles."""
        collection = self._collection_factory()
        for store in self._defaults.values():
            document = asdict(store)
            document.pop("id")
            collection.update_one({"_id": store.id}, {"$setOnInsert": document}, upsert=True)
        self.invalidate()

    def set_flags(self, store_id: str, **flags: bool) -> StoreConfig:
        if store_id not in self._defaults:
            raise UnknownStore(store_id)
        unknown = set(flags) - set(FLAG_FIELDS)
        if unknown or not flags:
            raise ValueError(f"flags must be a non-empty subset of {FLAG_FIELDS}, got {sorted(flags)}")
        if not all(isinstance(value, bool) for value in flags.values()):
            raise ValueError("flag values must be booleans")
        self.seed()
        self._collection_factory().update_one({"_id": store_id}, {"$set": flags})
        self.invalidate()
        return self.get(store_id)

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def _load(self) -> list[StoreConfig]:
        try:
            documents = {doc["_id"]: doc for doc in self._collection_factory().find({})}
        except mongo_errors.PyMongoError:
            logger.warning(
                "Store registry unavailable; using default store settings.",
                exc_info=True,
                extra={"Action": "stores.registry_unavailable", "Category": "dependency"},
            )
            return sorted(self._defaults.values(), key=lambda s: s.order)

        stores = []
        for store_id, default in self._defaults.items():
            document = documents.get(store_id) or {}
            overrides = {
                field: document[field]
                for field in (*FLAG_FIELDS, "name", "order", "website")
                if field in document and document[field] is not None
            }
            stores.append(replace(default, **overrides))
        return sorted(stores, key=lambda s: s.order)

    # -- reads --------------------------------------------------------------

    def all(self) -> list[StoreConfig]:
        with self._lock:
            now = self._clock()
            if self._cached is None or now - self._loaded_at >= self._ttl:
                self._cached = self._load()
                self._loaded_at = now
            return list(self._cached)

    def get(self, store_id: str) -> Optional[StoreConfig]:
        return next((store for store in self.all() if store.id == store_id), None)

    def enabled(self) -> list[StoreConfig]:
        return [store for store in self.all() if store.enabled]

    def is_enabled(self, store_id: str) -> bool:
        store = self.get(store_id)
        return bool(store and store.enabled)

    def scrape_enabled(self, store_id: str) -> bool:
        store = self.get(store_id)
        return bool(store and store.scrape_enabled)

    def loyalty_enabled(self, store_id: str) -> bool:
        store = self.get(store_id)
        return bool(store and store.loyalty_enabled)

    def resolve(self, requested: Optional[str]) -> list[str]:
        """Turn a ``stores`` query parameter into enabled store IDs, in order.

        Empty means every enabled store. Naming an unknown or disabled store is
        an error rather than a silent omission, so a client cannot mistake a
        hidden store for a store without results.
        """
        enabled_ids = [store.id for store in self.enabled()]
        if not requested or not requested.strip():
            return enabled_ids
        wanted = []
        for part in requested.split(","):
            store_id = part.strip().lower()
            if not store_id or store_id in wanted:
                continue
            if not STORE_ID_PATTERN.match(store_id) or store_id not in self._defaults:
                raise UnknownStore(store_id)
            if store_id not in enabled_ids:
                raise DisabledStore(store_id)
            wanted.append(store_id)
        return [store_id for store_id in enabled_ids if store_id in wanted]


def _registry_collection():
    from mongo import database_manager as db
    return db.get_database()["stores"]


registry = StoreRegistry(_registry_collection)
