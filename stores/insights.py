"""Store-neutral price statistics ("insights") and cross-store comparison.

Per store, one pass over its price history computes every statistic and the
result is cached for the day (rebuilt after the store's daily scrape). The
comparison between stores only uses products linked by barcode.

Prices use the neutral channels: ``regular`` (Tesco normal), ``promo`` (Tesco
discount) and ``loyalty`` (Tesco Clubcard, Auchan card price). Auchan card
prices are only known for part of the range (see docs/store-spike.md), so
comparisons report regular prices and best prices separately.
"""

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from pymongo import errors as mongo_errors

from mongo import database_manager as db
from stores import queries
from stores.ids import is_restricted_circulation


logger = logging.getLogger(__name__)

PRICE_TIERS = [
    (0, 1_000, "0–1 000"),
    (1_000, 5_000, "1 000–5 000"),
    (5_000, 10_000, "5 000–10 000"),
    (10_000, 20_000, "10 000–20 000"),
    (20_000, 50_000, "20 000–50 000"),
    (50_000, 100_000, "50 000–100 000"),
    (100_000, None, "100 000+"),
]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LIST_LIMIT = 500
BASKET_DAYS = 60
COMPARISON_MAX_AGE = timedelta(hours=1)
CACHE_PREFIX = "insights:"


def _tier(price: float) -> str:
    for low, high, label in PRICE_TIERS:
        if price >= low and (high is None or price < high):
            return label
    return PRICE_TIERS[-1][2]


def _best(regular, promo, loyalty) -> Optional[float]:
    values = [value for value in (regular, promo, loyalty) if isinstance(value, (int, float))]
    return min(values) if values else None


def _avg(values) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


# -- per store ---------------------------------------------------------------------

def compute_store_insights(store_id: str, today: date) -> dict:
    """Every per-store statistic in a single pass over the store's history."""
    today_s = today.isoformat()
    yesterday_s = (today - timedelta(days=1)).isoformat()
    month_ago_s = (today - timedelta(days=30)).isoformat()

    daily_regular = defaultdict(list)
    savings_by_date = defaultdict(float)
    weekday_discounts = defaultdict(list)
    tiers = {label: 0 for _, _, label in PRICE_TIERS}
    volatility = defaultdict(list)
    latest_regular, latest_promo, latest_loyalty = [], [], []
    # Paired samples: (regular, other) of the same product, so a channel or a
    # month is never compared against a different set of products.
    promo_pairs, loyalty_pairs, month_pairs = [], [], []
    today_regular, month_ago_regular = [], []
    top_discounts, price_drops = [], []
    total = active_today = 0

    for ref, name, _category, _gtin, rows in queries.adapter_for(store_id).iter_histories():
        total += 1
        if not rows:
            continue
        by_date = {row[0]: row for row in rows}
        latest = rows[-1]
        if latest[0] == today_s:
            active_today += 1

        recent = []
        for day, regular, promo, loyalty in rows:
            if regular is None:
                continue
            daily_regular[day].append(regular)
            if day >= month_ago_s:
                recent.append(regular)
            if promo is not None and regular > 0 and promo < regular:
                savings_by_date[day] += regular - promo
                try:
                    weekday_discounts[datetime.strptime(day, "%Y-%m-%d").weekday()].append((regular - promo) / regular * 100)
                except ValueError:
                    pass

        _, regular, promo, loyalty = latest
        if regular is not None:
            latest_regular.append(regular)
            tiers[_tier(regular)] += 1
            if len(recent) >= 2:
                mean = sum(recent) / len(recent)
                volatility[_tier(regular)].append(math.sqrt(sum((v - mean) ** 2 for v in recent) / len(recent)))
        if promo is not None:
            latest_promo.append(promo)
            if regular:
                promo_pairs.append((regular, promo))
        if loyalty is not None:
            latest_loyalty.append(loyalty)
            if regular:
                loyalty_pairs.append((regular, loyalty))

        today_row, yesterday_row, month_row = by_date.get(today_s), by_date.get(yesterday_s), by_date.get(month_ago_s)
        if today_row and today_row[1] is not None:
            today_regular.append(today_row[1])
            if today_row[2] is not None and today_row[1] > 0 and today_row[2] < today_row[1]:
                top_discounts.append({
                    "ref": ref, "name": name, "regular": today_row[1], "promo": today_row[2],
                    "pct_off": round((today_row[1] - today_row[2]) / today_row[1] * 100, 1),
                })
            if yesterday_row and yesterday_row[1] is not None and today_row[1] < yesterday_row[1]:
                price_drops.append({
                    "ref": ref, "name": name, "yesterday": yesterday_row[1], "today": today_row[1],
                    "drop_amount": round(yesterday_row[1] - today_row[1], 2),
                    "drop_pct": round((yesterday_row[1] - today_row[1]) / yesterday_row[1] * 100, 2),
                })
        if month_row and month_row[1] is not None:
            month_ago_regular.append(month_row[1])
            if today_row and today_row[1] is not None:
                month_pairs.append((month_row[1], today_row[1]))

    dates = sorted(daily_regular)
    first_avg = sum(daily_regular[dates[0]]) / len(daily_regular[dates[0]]) if dates else 0
    avg_today, avg_month_ago = _avg(today_regular), _avg(month_ago_regular)

    def paired_pct(pairs):
        """Change of the second value against the first, over the same products."""
        base = sum(first for first, _ in pairs)
        return round((sum(second for _, second in pairs) - base) / base * 100, 2) if base else None

    best_day = max(savings_by_date, key=savings_by_date.get) if savings_by_date else None

    top_discounts.sort(key=lambda item: item["pct_off"], reverse=True)
    price_drops.sort(key=lambda item: item["drop_pct"], reverse=True)
    avg_regular = _avg(latest_regular)
    return {
        "store": store_id,
        "date": today_s,
        "price_index": [
            {"date": day, "index": round(sum(daily_regular[day]) / len(daily_regular[day]) / first_avg * 100, 2)}
            for day in dates
        ] if first_avg else [],
        "product_counts": {"total": total, "active_today": active_today, "historical_only": total - active_today},
        "price_tiers": [{"tier": label, "count": tiers[label]} for _, _, label in PRICE_TIERS],
        "price_channels": {
            "avg_regular": avg_regular,
            "avg_promo": _avg(latest_promo),
            "avg_loyalty": _avg(latest_loyalty),
            "promo_vs_regular_pct": paired_pct(promo_pairs),
            "loyalty_vs_regular_pct": paired_pct(loyalty_pairs),
            "products_with_promo": len(latest_promo),
            "products_with_loyalty": len(latest_loyalty),
        },
        "best_shopping_day": {
            "date": best_day,
            "total_savings": round(savings_by_date[best_day], 2) if best_day else None,
        },
        "discount_by_weekday": [
            {"weekday": WEEKDAYS[index], "avg_pct_off": _avg(weekday_discounts[index]) or 0.0,
             "total_events": len(weekday_discounts[index])}
            for index in range(7)
        ],
        "volatility": [
            {"tier": label, "avg_volatility": round(sum(volatility[label]) / len(volatility[label]), 4) if volatility[label] else 0.0,
             "product_count": len(volatility[label])}
            for _, _, label in PRICE_TIERS
        ],
        "global_avg": {"avg_price": avg_regular, "product_count": len(latest_regular)},
        "inflation_30d": {
            "pct_change": paired_pct(month_pairs),
            "paired_products": len(month_pairs),
            "avg_today": avg_today,
            "avg_30d_ago": avg_month_ago,
            "date_today": today_s,
            "date_30d_ago": month_ago_s,
        },
        "top_discounts": top_discounts[:LIST_LIMIT],
        "price_drops": price_drops[:LIST_LIMIT],
    }


# -- cross-store comparison ----------------------------------------------------------

def compute_comparison(store_ids: list, today: date) -> dict:
    """Compare stores on products they all sell (same barcode, priced recently)."""
    cutoff = (today - timedelta(days=2)).isoformat()
    basket_from = (today - timedelta(days=BASKET_DAYS)).isoformat()
    current = {store_id: {} for store_id in store_ids}        # gtin -> (regular, best, category)
    histories = {store_id: defaultdict(dict) for store_id in store_ids}  # gtin -> date -> regular

    for store_id in store_ids:
        for _ref, _name, category, gtin, rows in queries.adapter_for(store_id).iter_histories():
            if not gtin or is_restricted_circulation(gtin) or not rows:
                continue
            day, regular, promo, loyalty = rows[-1]
            if day < cutoff or regular is None:
                continue
            best = _best(regular, promo, loyalty)
            previous = current[store_id].get(gtin)
            if previous is None or best < previous[1]:  # duplicate barcodes: keep the cheaper listing
                current[store_id][gtin] = (regular, best, category)
                histories[store_id][gtin] = {}
                for row in rows:
                    if row[0] >= basket_from and row[1] is not None:
                        histories[store_id][gtin][row[0]] = row[1]

    linked = set.intersection(*(set(current[store_id]) for store_id in store_ids)) if store_ids else set()
    cheapest_regular = {store_id: 0 for store_id in store_ids}
    cheapest_best = {store_id: 0 for store_id in store_ids}
    ties = {"regular": 0, "best": 0}
    index_sum = {store_id: 0.0 for store_id in store_ids}
    categories = defaultdict(lambda: {"products": 0, "index_sum": {store_id: 0.0 for store_id in store_ids}})

    for gtin in linked:
        regular = {store_id: current[store_id][gtin][0] for store_id in store_ids}
        best = {store_id: current[store_id][gtin][1] for store_id in store_ids}
        for prices, counts, label in ((regular, cheapest_regular, "regular"), (best, cheapest_best, "best")):
            low = min(prices.values())
            winners = [store_id for store_id, price in prices.items() if price == low]
            if len(winners) == 1:
                counts[winners[0]] += 1
            else:
                ties[label] += 1
        low_regular = min(regular.values())
        category = current[store_ids[0]][gtin][2] or "Other"
        categories[category]["products"] += 1
        for store_id in store_ids:
            relative = regular[store_id] / low_regular * 100 if low_regular else 100.0
            index_sum[store_id] += relative
            categories[category]["index_sum"][store_id] += relative

    count = len(linked)
    basket = []
    all_days = sorted({day for store_id in store_ids for gtin in linked for day in histories[store_id][gtin]})
    for day in all_days:
        items = [gtin for gtin in linked if all(day in histories[store_id][gtin] for store_id in store_ids)]
        if items:
            basket.append({
                "date": day,
                "items": len(items),
                "totals": {store_id: round(sum(histories[store_id][gtin][day] for gtin in items), 2) for store_id in store_ids},
            })

    return {
        "stores": store_ids,
        "date": today.isoformat(),
        "linked_products": count,
        "cheapest_by_regular_price": cheapest_regular,
        "cheapest_by_best_price": cheapest_best,
        "ties": ties,
        # 100 = cheapest store for that product; 110 = 10 % more expensive, on average.
        "price_index_vs_cheapest": {store_id: round(index_sum[store_id] / count, 2) if count else None for store_id in store_ids},
        "categories": sorted(
            (
                {"category": name, "products": data["products"],
                 "price_index_vs_cheapest": {s: round(data["index_sum"][s] / data["products"], 2) for s in store_ids}}
                for name, data in categories.items()
            ),
            key=lambda item: item["products"],
            reverse=True,
        ),
        "basket": basket,
        "category_source": store_ids[0] if store_ids else None,
        "note": "Best prices include loyalty-card prices; Auchan card prices are only partly visible.",
    }


# -- caching ---------------------------------------------------------------------------

def _cache():
    return db.get_database()["stats_cache"]


def _read(key: str, max_age: Optional[timedelta] = None):
    try:
        doc = _cache().find_one({"_id": key})
    except mongo_errors.PyMongoError:
        logger.warning("Insight cache unavailable.", exc_info=True)
        return None
    if not doc:
        return None
    if max_age is not None:
        try:
            if datetime.now() - datetime.fromisoformat(doc["computed_at"]) > max_age:
                return None
        except (KeyError, TypeError, ValueError):
            return None
    return doc.get("data")


def _write(key: str, data) -> None:
    try:
        _cache().replace_one({"_id": key}, {"_id": key, "data": data, "computed_at": datetime.now().isoformat()}, upsert=True)
    except mongo_errors.PyMongoError:
        logger.warning("Could not cache insight %s.", key, exc_info=True)


def _store_key(store_id: str, today: date) -> str:
    return f"{CACHE_PREFIX}store:{store_id}:{today.isoformat()}"


def store_insights(store_id: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    key = _store_key(store_id, today)
    data = _read(key)
    if data is None:
        data = compute_store_insights(store_id, today)
        _write(key, data)
    return data


def comparison(store_ids: list, today: Optional[date] = None) -> dict:
    today = today or date.today()
    key = f"{CACHE_PREFIX}compare:{','.join(store_ids)}:{today.isoformat()}"
    data = _read(key, max_age=COMPARISON_MAX_AGE)
    if data is None:
        data = compute_comparison(store_ids, today)
        _write(key, data)
    return data


def rebuild_store(store_id: str, clock: Callable[[], date] = date.today) -> bool:
    """Recompute a store's insights after its scrape. Never raises."""
    today = clock()
    try:
        _write(_store_key(store_id, today), compute_store_insights(store_id, today))
        _cache().delete_many({"_id": {"$regex": f"^{CACHE_PREFIX}compare:"}})
    except Exception:
        logger.exception(
            "Rebuilding %s insights failed.", store_id,
            extra={"Action": "insights.rebuild_failed", "Category": "job", "Store": store_id},
        )
        return False
    logger.info(
        "Rebuilt %s insights.", store_id,
        extra={"Action": "insights.rebuilt", "Category": "job", "Store": store_id},
    )
    return True
