"""In-memory evaluation of price drops against active alerts."""

from typing import Iterable, Optional


def _discount_pct(old: Optional[float], new: float) -> Optional[float]:
    if old is None or old <= 0:
        return None
    return max(0.0, (old - new) / old * 100.0)


def evaluate(
    alerts: Iterable[dict],
    drop_map: dict[str, dict],
) -> list[dict]:
    """Return triggered alerts enriched with the originating drop info.

    ``drop_map`` is keyed by productId and carries ``newPrice`` and optionally
    ``oldPrice`` and ``productName`` (forwarded from the scraper).
    """
    triggered: list[dict] = []
    for alert in alerts:
        drop = drop_map.get(alert["productId"])
        if drop is None:
            continue

        new_price = drop["newPrice"]
        alert_type = alert["alertType"]
        matched = False
        ratio: Optional[float] = None

        if alert_type == "TARGET_PRICE":
            target = alert.get("targetPrice")
            if target is not None and new_price <= target:
                matched = True
                ratio = _discount_pct(target, new_price)
        elif alert_type == "PERCENTAGE_DROP":
            base = alert.get("basePriceAtCreation")
            threshold = alert.get("dropPercentage")
            if base and threshold:
                pct = _discount_pct(base, new_price) or 0.0
                if pct >= threshold:
                    matched = True
                    ratio = pct

        if not matched:
            continue

        old_price = drop.get("oldPrice")
        triggered.append(
            {
                "userId": alert["userId"],
                "productId": alert["productId"],
                "productName": drop.get("productName"),
                "newPrice": new_price,
                "oldPrice": old_price,
                "alertType": alert_type,
                # Sort key: prefer the actual market drop (old → new) when we know
                # the previous price; fall back to the alert's own delta otherwise.
                "discountPct": _discount_pct(old_price, new_price) or ratio or 0.0,
            }
        )
    return triggered


def group_by_user(triggered: list[dict]) -> dict[str, list[dict]]:
    by_user: dict[str, list[dict]] = {}
    for item in triggered:
        by_user.setdefault(item["userId"], []).append(item)
    for items in by_user.values():
        items.sort(key=lambda x: x.get("discountPct", 0.0), reverse=True)
    return by_user
