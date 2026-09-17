"""Map auchan.hu API products to the stored Auchan document and to offers."""

import re
import unicodedata
from typing import Optional

from stores import offers
from stores.ids import normalize_gtin


STORE_ID = "auchan"
PRODUCT_URL = "https://auchan.hu/shop/{slug}.p-{sku}"
OWN_BRAND_FLAG = "Auchan Kedvenc"
LOYALTY_FLAG_KEY = "flag_loyalty_price"

_UNITS = {"KG": "kg", "LITER": "l", "DB": "db", "M": "m"}


class UnexpectedProductShape(ValueError):
    pass


def slugify(text: str) -> str:
    """Same rule as the shop: drop punctuation, join words with dashes ("0,25 l" -> "025-l")."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9\s-]", "", ascii_text)
    return re.sub(r"[\s-]+", "-", words).strip("-")


def _gross(price: Optional[dict], key: str = "gross") -> Optional[float]:
    if not isinstance(price, dict):
        return None
    value = price.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _card_price(regular, unit_loyalty: float, pack_size: float, discount_pct) -> float:
    """Shelf card price from the card unit price, choosing the more precise route.

    The unit price is rounded to whole forints, so multiplying it back by the
    pack size is off by up to half a forint per unit: exact for a 75 g pack,
    but 15 Ft off for 44 pieces (21 Ft x 44 = 924, shelf price 909). The whole
    discount percentage is off by up to 0.5 % of the regular price instead.
    Use whichever error bound is smaller.
    """
    by_unit = float(round(unit_loyalty * pack_size))
    if not isinstance(regular, (int, float)) or not isinstance(discount_pct, (int, float)) or discount_pct <= 0:
        return by_unit
    unit_error = 0.5 * pack_size
    percent_error = 0.005 * regular
    if percent_error < unit_error:
        return float(round(regular * (1 - discount_pct / 100)))
    return by_unit


def price_fields(variant: dict) -> dict:
    """Regular, promotional and loyalty-card price, with the unit price per kg/l/piece.

    Loose products are sold by weight; their list price is an estimate for one
    typical piece, so the per-kg unit price is used instead, matching how Tesco
    prices weighed products.

    The card price itself is only sent to logged-in card holders, but anonymous
    responses include the discounted card *unit* price (``loyaltyUnitPrice``);
    unit price times pack size gives the shelf card price.
    """
    price = variant.get("price") or {}
    package = variant.get("packageInfo") or {}
    unit_price_info = package.get("unitPrice") or {}
    loyalty_unit_info = package.get("loyaltyUnitPrice") or {}
    loose = bool((variant.get("loose") or {}).get("loose"))

    regular = _gross(price)
    promo = _gross(price, "grossDiscounted") if price.get("isDiscounted") else None
    unit_regular = _gross(unit_price_info)
    unit_promo = _gross(unit_price_info, "grossDiscounted") if unit_price_info.get("isDiscounted") else None
    unit_loyalty = _gross(loyalty_unit_info, "grossDiscounted") if loyalty_unit_info.get("isDiscounted") else None
    pack_size = package.get("packageSize")

    loyalty = None
    if loose and unit_regular is not None:
        regular, promo, loyalty = unit_regular, unit_promo, unit_loyalty
    elif unit_loyalty is not None and isinstance(pack_size, (int, float)) and pack_size > 0:
        loyalty = _card_price(regular, unit_loyalty, pack_size, loyalty_unit_info.get("discountPercentage"))
    if promo is not None and regular is not None and promo >= regular:
        promo = None
    if loyalty is not None and regular is not None and loyalty >= regular:
        loyalty = None

    package_unit = package.get("packageUnit")
    return offers.prices(
        regular=regular,
        promo=promo,
        loyalty=loyalty,
        unit_price=unit_regular,
        unit=_UNITS.get(str(package_unit).upper(), str(package_unit).lower() if package_unit else None),
    )


def document_fields(product: dict) -> dict:
    """Static and current fields for one API product (no history)."""
    variant = product.get("selectedVariant") or product.get("defaultVariant")
    if not isinstance(variant, dict) or product.get("id") is None or not variant.get("name"):
        raise UnexpectedProductShape(f"product {product.get('id')!r} has no usable variant")

    categories = sorted(
        (c for c in product.get("categories") or [] if isinstance(c, dict)),
        key=lambda c: c.get("level", 0),
    )
    flags = [f for f in variant.get("flags") or [] if isinstance(f, dict)]
    flag_names = [f.get("name") for f in flags if f.get("name")]
    package = variant.get("packageInfo") or {}
    loose = bool((variant.get("loose") or {}).get("loose"))
    availability = (variant.get("cartInfo") or {}).get("availability")
    ean = variant.get("eanCode") or product.get("eancode")
    brand = variant.get("brandName") or product.get("brandName")
    sku = variant.get("sku")

    return {
        "store_product_id": str(product["id"]),
        "variant_id": variant.get("id"),
        "sku": str(sku) if sku is not None else None,
        "name": variant["name"].strip(),
        "brand": brand,
        "ean": str(ean) if ean else None,
        "gtin_norm": normalize_gtin(ean),
        "category_path": [c.get("name") for c in categories if c.get("name")],
        "category_ids": [c.get("id") for c in categories if c.get("id") is not None],
        "pack_size": 1.0 if loose else package.get("packageSize"),
        "pack_unit": price_fields(variant)["unit"],
        "is_loose": loose,
        "is_non_food": bool(product.get("isNonFood")),
        "adults_only": bool(product.get("adultsOnly")),
        "own_brand": OWN_BRAND_FLAG in flag_names or str(brand or "").lower().startswith("auchan"),
        "loyalty_offer": any(f.get("flag") == LOYALTY_FLAG_KEY for f in flags),
        "flags": flag_names,
        "image_url": (variant.get("media") or {}).get("mainImage"),
        "url": PRODUCT_URL.format(slug=slugify(variant["name"]), sku=sku) if sku else None,
        "availability": "available" if availability == "available" else "unavailable",
        "prices": price_fields(variant),
        "promo_valid_to": (package.get("unitPrice") or {}).get("discountValidTo"),
        "loyalty_valid_to": (package.get("loyaltyUnitPrice") or {}).get("discountValidTo"),
        "detail_sections": [s for s in variant.get("details") or [] if isinstance(s, str)],
    }


def offer_from_doc(doc: dict) -> dict:
    current = doc.get("current") or {}
    return offers.build_offer(
        store_id=STORE_ID,
        store_product_id=doc["_id"],
        name=doc.get("name"),
        gtin=doc.get("ean"),
        brand=doc.get("brand"),
        image_url=doc.get("image_url"),
        category_path=doc.get("category_path") or [],
        pack_size=doc.get("pack_size"),
        pack_unit=doc.get("pack_unit"),
        availability=doc.get("availability"),
        price_set=offers.prices(**{k: current.get(k) for k in ("regular", "promo", "loyalty", "unit_price", "unit")}),
        price_date=current.get("date"),
        flags=doc.get("flags") or [],
        url=doc.get("url"),
        is_weighed=bool(doc.get("is_loose")),
    )


def details_text(sections: list) -> dict:
    """Description and ingredients from the details endpoint, for embeddings."""
    result = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        kind = section.get("sectionType")
        text = section.get("description")
        if kind in ("description", "ingredients") and isinstance(text, str) and text.strip():
            result[kind] = text.strip()[:4000]
    return result
