"""In-memory evaluation of price drops against active alerts."""

from collections import defaultdict
from typing import Iterable, Optional


def _discount_pct(old: Optional[float], new: float) -> Optional[float]:
    if old is None or old <= 0:
        return None
    return max(0.0, (old - new) / old * 100.0)


def _alert_matches(alert: dict, new_price: float) -> tuple[bool, Optional[float]]:
    alert_type = alert["alertType"]
    if alert_type == "TARGET_PRICE":
        target = alert.get("targetPrice")
        if target is not None and new_price <= target:
            return True, _discount_pct(target, new_price)
    elif alert_type == "PERCENTAGE_DROP":
        base = alert.get("basePriceAtCreation")
        threshold = alert.get("dropPercentage")
        if base and threshold:
            pct = _discount_pct(base, new_price) or 0.0
            if pct >= threshold:
                return True, pct
    return False, None


def evaluate(
    alerts: Iterable[dict],
    drops: Iterable[dict],
    enabled_stores: Optional[set] = None,
) -> list[dict]:
    """Return triggered alerts enriched with the originating drop.

    Each drop has ``ref`` (offer reference), ``store``, optional ``groupId``,
    ``newPrice`` and optionally ``oldPrice`` and ``productName``. An alert
    watching an offer matches that offer's drop; an alert watching a group
    matches a drop of any member offer. Only stores the alert watches and that
    are enabled count, so one group alert can fire for two stores in one run.
    """
    by_key: dict[str, list[dict]] = defaultdict(list)
    for drop in drops:
        by_key[drop["ref"]].append(drop)
        if drop.get("groupId"):
            by_key[drop["groupId"]].append(drop)

    triggered: list[dict] = []
    for alert in alerts:
        target = alert.get("target") or f"tesco:{alert['productId']}"
        stores = alert.get("stores") or ["tesco"]
        for drop in by_key.get(target, []):
            if drop["store"] not in stores:
                continue
            if enabled_stores is not None and drop["store"] not in enabled_stores:
                continue
            matched, ratio = _alert_matches(alert, drop["newPrice"])
            if not matched:
                continue
            old_price = drop.get("oldPrice")
            triggered.append(
                {
                    "userId": alert["userId"],
                    "productId": drop["ref"],
                    "target": target,
                    "store": drop["store"],
                    "productName": drop.get("productName"),
                    "newPrice": drop["newPrice"],
                    "oldPrice": old_price,
                    "alertType": alert["alertType"],
                    # Sort key: prefer the actual market drop (old → new) when we know
                    # the previous price; fall back to the alert's own delta otherwise.
                    "discountPct": _discount_pct(old_price, drop["newPrice"]) or ratio or 0.0,
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
