"""The store-neutral product view returned by the multi-store API.

Every store adapter maps its own documents to these shapes, so callers never
see store-specific field names (Tesco ``clubcard`` becomes ``loyalty``).
"""

from typing import Iterable, Optional

from stores.ids import is_restricted_circulation, make_ref, normalize_gtin


GROUP_PREFIX = "g:"


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def prices(regular=None, promo=None, loyalty=None, unit_price=None, unit=None) -> dict:
    return {
        "regular": _number(regular),
        "promo": _number(promo),
        "loyalty": _number(loyalty),
        "unit_price": _number(unit_price),
        "unit": unit or None,
    }


def effective_price(price_set: dict) -> Optional[float]:
    """Lowest price a shopper can get: regular, promo or loyalty."""
    candidates = [price_set.get(key) for key in ("regular", "promo", "loyalty")]
    numeric = [value for value in candidates if isinstance(value, (int, float))]
    return min(numeric) if numeric else None


def discount_ratio(price_set: dict) -> float:
    """Best saving against the regular price, 0.0-1.0."""
    regular = price_set.get("regular")
    best = effective_price(price_set)
    if not regular or best is None or best >= regular:
        return 0.0
    return (regular - best) / regular


def build_offer(
    *,
    store_id: str,
    store_product_id,
    name,
    gtin=None,
    brand=None,
    image_url=None,
    category_path: Iterable = (),
    pack_size=None,
    pack_unit=None,
    availability=None,
    price_set: Optional[dict] = None,
    price_date=None,
    flags: Iterable = (),
    url=None,
    is_weighed: Optional[bool] = None,
) -> dict:
    gtin_norm = normalize_gtin(gtin)
    price_set = price_set or prices()
    if is_weighed is None:
        is_weighed = is_restricted_circulation(gtin_norm)
    return {
        "store": store_id,
        "ref": make_ref(store_id, store_product_id),
        "store_product_id": str(store_product_id),
        "gtin": gtin_norm,
        "group_id": group_id_for(gtin_norm),
        "is_weighed": is_weighed,
        "name": name,
        "brand": brand or None,
        "image_url": image_url or None,
        "category_path": [part for part in category_path if part],
        "pack_size": _number(pack_size),
        "pack_unit": pack_unit or None,
        "availability": availability or None,
        "prices": price_set,
        "effective_price": effective_price(price_set),
        "discount_ratio": round(discount_ratio(price_set), 4),
        "price_date": price_date or None,
        "flags": [flag for flag in flags if flag],
        "url": url or None,
    }


def group_id_for(gtin_norm: Optional[str]) -> Optional[str]:
    """Group key linking the same product across stores, or None if unlinkable."""
    if not gtin_norm or is_restricted_circulation(gtin_norm):
        return None
    return f"{GROUP_PREFIX}{gtin_norm}"


def parse_group_id(group_id: str) -> Optional[str]:
    """Return the normalised GTIN of a group ID, or None if it is not one."""
    if not isinstance(group_id, str) or not group_id.startswith(GROUP_PREFIX):
        return None
    gtin_norm = normalize_gtin(group_id[len(GROUP_PREFIX):])
    if gtin_norm != group_id[len(GROUP_PREFIX):] or is_restricted_circulation(gtin_norm):
        return None
    return gtin_norm


def history_row(date, price_set: dict, availability=None) -> dict:
    return {"date": date, **price_set, "availability": availability}
