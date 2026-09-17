"""What an alert watches: one store listing or a product across stores.

``target`` is an offer reference (``tesco:121262922``) or a barcode group
(``g:54026193``). ``productId`` is kept for older clients: the browser extension
matches Tesco alerts by the bare tpnc, so Tesco offer alerts keep it.
"""

from typing import Iterable, Optional

from stores.ids import InvalidReference, parse_ref
from stores.offers import GROUP_PREFIX, parse_group_id


KNOWN_STORES = ("tesco", "auchan")
LEGACY_STORE = "tesco"


class InvalidTarget(ValueError):
    pass


def normalize(value: str) -> tuple[str, str]:
    """Return ``(target, product_id)`` for a target, reference or bare Tesco tpnc."""
    value = (value or "").strip()
    if not value:
        raise InvalidTarget("a product is required")
    if value.startswith(GROUP_PREFIX):
        if parse_group_id(value) is None:
            raise InvalidTarget(f"invalid product group: {value}")
        return value, value
    if ":" in value:
        try:
            store_id, store_product_id = parse_ref(value)
        except InvalidReference as exc:
            raise InvalidTarget(str(exc)) from exc
        if store_id not in KNOWN_STORES:
            raise InvalidTarget(f"unknown store: {store_id}")
        return value, store_product_id if store_id == LEGACY_STORE else value
    return f"{LEGACY_STORE}:{value}", value


def store_of(target: str) -> Optional[str]:
    """The store of an offer target, or None for a group."""
    if target.startswith(GROUP_PREFIX):
        return None
    return target.split(":", 1)[0]


def resolve_stores(target: str, requested: Optional[Iterable[str]], enabled: Iterable[str]) -> list[str]:
    """Stores an alert watches.

    An offer alert watches its own store. A group alert watches the requested
    stores, or every enabled store when none are given.
    """
    offer_store = store_of(target)
    if offer_store is not None:
        return [offer_store]
    enabled = [store for store in KNOWN_STORES if store in set(enabled)]
    if requested is None:
        stores = enabled
    else:
        wanted = {store.strip().lower() for store in requested if store and store.strip()}
        unknown = wanted - set(KNOWN_STORES)
        if unknown:
            raise InvalidTarget(f"unknown store: {sorted(unknown)[0]}")
        stores = [store for store in KNOWN_STORES if store in wanted]
    if not stores:
        raise InvalidTarget("select at least one store")
    return stores
