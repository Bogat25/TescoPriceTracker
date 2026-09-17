"""Identifiers shared by every store.

An offer reference names one listing in one store (``tesco:121262922``). A
normalised GTIN links listings of the same product across stores.
"""

import re
from typing import Optional


STORE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_NON_DIGITS = re.compile(r"\D")

# Shorter codes are internal article numbers, not barcodes.
_MIN_GTIN_DIGITS = 7


class InvalidReference(ValueError):
    """Raised when an offer reference is not ``{store}:{store_product_id}``."""


def normalize_gtin(value) -> Optional[str]:
    """Return the GTIN digits without leading zeros, or None when unusable.

    Tesco stores GTIN-14 with leading zeros (``00000054026193``) while other
    stores send EAN-8 or EAN-13 (``54026193``); both must compare equal.
    """
    if value is None:
        return None
    digits = _NON_DIGITS.sub("", str(value)).lstrip("0")
    if len(digits) < _MIN_GTIN_DIGITS:
        return None
    return digits


def is_restricted_circulation(gtin_norm: Optional[str]) -> bool:
    """True for in-store codes (EAN-13 prefix 2), e.g. weighed fresh products.

    Each retailer assigns these on its own, so equal codes in two stores do not
    mean the same product and must never be linked.
    """
    return bool(gtin_norm) and len(gtin_norm) == 13 and gtin_norm.startswith("2")


def make_ref(store_id: str, store_product_id) -> str:
    return f"{store_id}:{store_product_id}"


def parse_ref(ref: str) -> tuple[str, str]:
    store_id, sep, store_product_id = (ref or "").partition(":")
    if not sep or not STORE_ID_PATTERN.match(store_id) or not store_product_id:
        raise InvalidReference(f"invalid offer reference: {ref!r}")
    return store_id, store_product_id
