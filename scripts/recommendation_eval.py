"""Measure the recommender, so its quality is a number rather than an impression.

Three modes, because they need different access:

    # anywhere, against the live site - no database needed
    python scripts/recommendation_eval.py api

    # inside the api container - the engine itself, with synthetic seeds.
    # The absolute path matters: that container's working directory is
    # /app/backend-api, so a relative scripts/... path misses.
    docker exec tesco-price-tracker-api python /app/scripts/recommendation_eval.py seeds

    # inside the api container - leave-one-out over real alerts
    docker exec tesco-price-tracker-api python /app/scripts/recommendation_eval.py holdout

Settings can be overridden per run, so a change can be measured before it is
adopted. The random seed is fixed, so two runs compare like for like:

    ... recommendation_eval.py seeds --oversearch 2.5 --max-per-brand 99   # as it was
    ... recommendation_eval.py seeds --oversearch 6                        # as it is

Everything is read-only. The holdout mode reads alerts, which are user data, so
it reports aggregates only: no user id, no watched product, ever leaves it.

What the numbers mean is written up in docs/recommendation-eval.md.
"""

import argparse
import json
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter


DEFAULT_BASE = "https://price-tracker.gavaller.com/api/prices"
USER_AGENT = "price-tracker-receval/1.0"   # the edge answers the default agent with 403
LIMIT = 24                                 # a page of recommendations
SEEDS = 40
HOLDOUT_MIN_ALERTS = 2


# -- shared -------------------------------------------------------------------------

def row_key(row: dict) -> str:
    return row.get("group_id") or row["offers"][0]["ref"]


def discount_of(row: dict) -> float:
    return max((offer.get("discount_ratio") or 0.0 for offer in row["offers"]), default=0.0)


def stores_of(row: dict) -> set:
    return {offer["store"] for offer in row["offers"]}


def share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def report(title: str, rows: list) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name:<{width}}  {value}")


# -- mode: api ----------------------------------------------------------------------

def get(base: str, path: str, **params):
    url = f"{base}{path}?{urllib.parse.urlencode(params)}" if params else f"{base}{path}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    return body, time.perf_counter() - started


def evaluate_api(base: str) -> int:
    """What can be measured without a login: the cold-start list everyone sees."""
    stores, _ = get(base, "/stores")
    store_ids = [store["id"] for store in stores["stores"]]
    print(f"stores: {', '.join(store_ids)}")

    catalogue, _ = get(base, "/browse", limit=100, sort_by="name")
    catalogue_discount = statistics.fmean(discount_of(row) for row in catalogue["results"])

    for selection in ([""] + store_ids if len(store_ids) > 1 else [""]):
        body, seconds = get(base, "/recommended/cold", limit=LIMIT, stores=selection)
        rows = body["results"]
        by_store = Counter(store for row in rows for store in stores_of(row))
        report(f"cold start (stores={selection or 'all'})", [
            ("rows", len(rows)),
            ("type", body["type"]),
            ("latency", f"{seconds:.2f} s"),
            ("mean discount", f"{statistics.fmean(discount_of(r) for r in rows):.3f}"),
            ("catalogue mean discount", f"{catalogue_discount:.3f}"),
            ("rows priced by both stores", share(sum(1 for r in rows if len(stores_of(r)) > 1), len(rows))),
            ("offers per store", dict(by_store)),
        ])

    print("\nPersonal picks need a signed-in user; run the 'seeds' mode for those.")
    return 0


# -- modes that need the engine ------------------------------------------------------

def load_engine():
    try:
        from stores import categories, queries, recommendations, semantic
        from stores.registry import registry
    except ImportError as exc:
        print(f"the engine is not importable here ({exc}).", file=sys.stderr)
        print("Run this mode inside the api container, or use the 'api' mode.", file=sys.stderr)
        raise SystemExit(2)
    return categories, queries, recommendations, semantic, registry


def cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def diversity(rows: list, semantic_module) -> float:
    """Mean pairwise distance inside a result list: 0 means all the same thing."""
    refs = [row["offers"][0]["ref"] for row in rows]
    try:
        vectors = list(semantic_module.vectors_for(refs).values())
    except Exception:
        return float("nan")
    if len(vectors) < 2:
        return float("nan")
    pairs = [1 - cosine(vectors[i], vectors[j])
             for i in range(len(vectors)) for j in range(i + 1, len(vectors))]
    return statistics.fmean(pairs)


def pick_seeds(categories_module, queries_module, store_ids: list, wanted: int) -> list:
    """One product per category, spread over the catalogue, each with a vector."""
    listing = categories_module.mapping().listing(store_ids)
    listing = [c for c in listing if c["products"] >= 10]
    random.shuffle(listing)
    seeds = []
    for category in listing[:wanted]:
        page = queries_module.browse(store_ids, 0, 3, "name", "asc", category["id"])
        for row in page["results"]:
            offer = row["offers"][0]
            seeds.append({"ref": offer["ref"], "store": offer["store"], "category": category["id"],
                          "name": offer["name"]})
            break
    return seeds


def evaluate_seeds(limit: int, count: int, oversearch=None, per_brand=None) -> int:
    """Recommend for a synthetic watcher of one product, and see what comes back."""
    categories, queries, recommendations, semantic, registry = load_engine()
    if oversearch is not None:
        recommendations.OVERSEARCH = oversearch
    if per_brand is not None:
        recommendations.MAX_PER_BRAND = per_brand
    print(f"oversearch={recommendations.OVERSEARCH} max_per_brand={recommendations.MAX_PER_BRAND}")
    store_ids = [store.id for store in registry.enabled()]
    seeds = pick_seeds(categories, queries, store_ids, count)
    if not seeds:
        print("no categories with enough products; build the mapping first "
              "(python -m stores.admin categories)", file=sys.stderr)
        return 2
    print(f"{len(seeds)} seeds over {len(store_ids)} stores, {limit} recommendations each")

    baseline = recommendations.rows(store_ids, limit, [])["results"]
    baseline_keys = {row_key(row) for row in baseline}

    in_category, cross_store, personalised, overlaps, latencies = [], [], 0, [], []
    discounts, diversities, reachable = [], [], set()
    mapping = categories.mapping()

    for seed in seeds:
        alerts = [{"target": seed["ref"], "createdAt": "2026-01-01T00:00:00"}]
        started = time.perf_counter()
        answer = recommendations.rows(store_ids, limit, alerts)
        latencies.append(time.perf_counter() - started)
        rows = answer["results"][: answer["personalized_count"]]
        if not rows:
            continue
        personalised += 1
        reachable.update(row_key(row) for row in rows)

        same = sum(1 for row in rows
                   if any(mapping.category_for(o["store"], o.get("category_path")) == seed["category"]
                          for o in row["offers"]))
        in_category.append(share(same, len(rows)))
        other = sum(1 for row in rows if seed["store"] not in stores_of(row))
        cross_store.append(share(other, len(rows)))
        overlaps.append(share(len({row_key(r) for r in rows} & baseline_keys), len(rows)))
        discounts.append(statistics.fmean(discount_of(row) for row in rows))
        diversities.append(diversity(rows, semantic))

    if not in_category:
        print("no seed produced personal picks - are the products vectorised?", file=sys.stderr)
        return 1

    clean = [d for d in diversities if d == d]   # drop NaN
    report("personal picks from a single watched product", [
        ("seeds that produced picks", f"{personalised}/{len(seeds)}"),
        ("in the seed's category", f"{statistics.fmean(in_category):.3f}"),
        ("from a store the seed's store is not", f"{statistics.fmean(cross_store):.3f}"),
        ("overlap with the discount-only list", f"{statistics.fmean(overlaps):.3f}"),
        ("mean discount of picks", f"{statistics.fmean(discounts):.3f}"),
        ("mean discount, discount-only list", f"{statistics.fmean(discount_of(r) for r in baseline):.3f}"),
        ("intra-list diversity", f"{statistics.fmean(clean):.3f}" if clean else "n/a"),
        ("distinct products reachable", len(reachable)),
        ("median latency", f"{statistics.median(latencies):.2f} s"),
    ])
    print("\nLow overlap means personalisation is doing something the discounts do not.")
    return 0


def evaluate_holdout(limit: int) -> int:
    """Hide each user's newest alert and see whether it comes back in the picks."""
    categories, queries, recommendations, semantic, registry = load_engine()
    from mongo import database_manager as db

    store_ids = [store.id for store in registry.enabled()]
    alerts_db = db.get_database().client[_alerts_db_name()]
    grouped: dict = {}
    for alert in alerts_db["alerts"].find({"enabled": True}, {"userId": 1, "target": 1, "createdAt": 1, "_id": 0}):
        grouped.setdefault(alert.get("userId"), []).append(alert)

    usable = {user: sorted(items, key=lambda a: a.get("createdAt") or "")
              for user, items in grouped.items() if len(items) >= HOLDOUT_MIN_ALERTS}
    print(f"users with alerts: {len(grouped)} | usable (>= {HOLDOUT_MIN_ALERTS}): {len(usable)} "
          f"| alerts: {sum(len(v) for v in grouped.values())}")
    if not usable:
        print("\nToo few users watch more than one product for leave-one-out to mean anything.")
        print("Report that honestly rather than reporting a hit rate over two users.")
        return 0

    baseline_keys = {row_key(row) for row in recommendations.rows(store_ids, limit, [])["results"]}
    hits, reciprocal, baseline_hits = 0, [], 0
    for items in usable.values():
        held_out, history = items[-1], items[:-1]
        target = str(held_out.get("target") or "")
        wanted = _target_keys(target, store_ids, queries)
        if not wanted:
            continue
        answer = recommendations.rows(store_ids, limit, history)
        keys = [row_key(row) for row in answer["results"][: answer["personalized_count"]]]
        position = next((i for i, key in enumerate(keys, start=1) if key in wanted), None)
        if position:
            hits += 1
            reciprocal.append(1 / position)
        if wanted & baseline_keys:
            baseline_hits += 1

    report(f"leave-one-out over {len(usable)} users, top {limit}", [
        ("hit rate", f"{share(hits, len(usable)):.3f}"),
        ("MRR", f"{statistics.fmean(reciprocal):.3f}" if reciprocal else "0.000"),
        ("hit rate, discount-only baseline", f"{share(baseline_hits, len(usable)):.3f}"),
    ])
    if len(usable) < 20:
        print(f"\n{len(usable)} users is too small to be conclusive. Report it as indicative.")
    return 0


def _alerts_db_name() -> str:
    import os
    return os.environ.get("MONGO_ALERTS_DB_NAME", "tesco_alerts")


def _target_keys(target: str, store_ids: list, queries_module) -> set:
    """Every row key the held-out alert could match."""
    if target.startswith("g:"):
        return {target}
    if ":" in target:
        store_id, product_id = target.split(":", 1)
        if store_id not in store_ids:
            return set()
        found = queries_module.adapter_for(store_id).find_by_ids([product_id])
        return {row_key({"group_id": o.get("group_id"), "offers": [o]}) for o in found}
    return set()


# -- entry point ---------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="recommendation_eval", description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("api", "seeds", "holdout"))
    parser.add_argument("--base", default=DEFAULT_BASE, help="API base for the 'api' mode")
    parser.add_argument("--limit", type=int, default=LIMIT)
    parser.add_argument("--seeds", type=int, default=SEEDS)
    parser.add_argument("--seed", type=int, default=20260918, help="random seed, so runs compare")
    parser.add_argument("--oversearch", type=float, help="override, to compare settings without a deploy")
    parser.add_argument("--max-per-brand", type=int, dest="per_brand", help="override the brand cap")
    args = parser.parse_args(argv)
    random.seed(args.seed)

    if args.mode == "api":
        return evaluate_api(args.base)
    if args.mode == "seeds":
        return evaluate_seeds(args.limit, args.seeds, args.oversearch, args.per_brand)
    return evaluate_holdout(args.limit)


if __name__ == "__main__":
    sys.exit(main())
