"""Tell the alert service about a store's price drops after its daily scrape.

The Tesco scraper has its own sender (``scraper._notify_alert_service``); this
module serves the other stores with the same payload and duplicate protection.
"""

import logging
import os
from datetime import date, timedelta
from typing import Optional

import requests

from stores import queries
from stores.offers import group_id_for


logger = logging.getLogger(__name__)


def _best(regular, promo, loyalty) -> Optional[float]:
    values = [value for value in (regular, promo, loyalty) if isinstance(value, (int, float))]
    return float(min(values)) if values else None


def todays_drops(store_id: str, today: date) -> list[dict]:
    """Offers whose best price today is lower than on their previous priced day."""
    today_s = today.isoformat()
    week_ago = (today - timedelta(days=7)).isoformat()
    drops = []
    for ref, name, _category, gtin_norm, rows in queries.adapter_for(store_id).iter_histories():
        if len(rows) < 2 or rows[-1][0] != today_s:
            continue
        previous = rows[-2]
        if previous[0] < week_ago:
            continue  # back after a long absence: not a price drop
        new_price, old_price = _best(*rows[-1][1:]), _best(*previous[1:])
        if new_price is None or old_price is None or new_price >= old_price:
            continue
        drops.append({
            "productId": ref,
            "store": store_id,
            "groupId": group_id_for(gtin_norm),
            "productName": name,
            "oldPrice": old_price,
            "newPrice": new_price,
        })
    return drops


def notify(store_id: str, today: date) -> bool:
    """Send today's drops. True once nothing is left to deliver."""
    url = os.environ.get("ALERT_SERVICE_TRIGGER_URL", "http://alert-service:8080/internal/trigger")
    token = os.environ.get("INTERNAL_TRIGGER_TOKEN", "")
    if not token:
        logger.info("INTERNAL_TRIGGER_TOKEN not set; skipping %s price-drop alerts.", store_id)
        return True
    try:
        drops = todays_drops(store_id, today)
    except Exception:
        logger.warning("Failed to compute %s price drops.", store_id, exc_info=True,
                       extra={"Action": "alerts.drops_failed", "Category": "job", "Store": store_id})
        return False
    if not drops:
        logger.info("No %s price drops to send to the alert service.", store_id)
        return True

    from logging_setup import correlation_headers
    headers = {"X-Internal-Token": token, **correlation_headers()}
    try:
        response = requests.post(
            url, json={"drops": drops, "runKey": f"{store_id}:{today.isoformat()}"}, headers=headers, timeout=60,
        )
    except requests.RequestException:
        logger.warning("Alert-service trigger failed.", exc_info=True,
                       extra={"Action": "alerts.trigger_failed", "Category": "upstream", "Store": store_id})
        return False
    if response.status_code != 200:
        logger.warning("Alert-service trigger non-200: %s", response.status_code,
                       extra={"Action": "alerts.trigger_failed", "Category": "upstream",
                              "HttpStatus": response.status_code, "Store": store_id})
        return False
    logger.info("Alert-service accepted %d %s price drops.", len(drops), store_id,
                extra={"Action": "alerts.trigger_accepted", "Category": "job", "Store": store_id})
    return True
