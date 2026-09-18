"""Measure search quality for text, semantic and hybrid search against the live API.

Each query has a relevance rule: a result row is relevant when every regular
expression in ``all`` matches the text of one of its offers (name and category
path). Rules were written before looking at any result, so the numbers are not
tuned to a mode. Metrics per mode, over the top 10 rows:

* precision@10: relevant rows / 10 (fewer than 10 results count as misses)
* MRR: mean of 1 / rank of the first relevant row (0 when none in the top 10)
* zero-result queries

``--calibrate`` also sweeps the semantic similarity threshold: for each value it
reports semantic precision@10 on the labelled queries and how many results
nonsense queries still get, which is how ``SEMANTIC_MIN_SCORE`` was chosen.

    python scripts/search_eval.py [--base URL] [--stores tesco,auchan] [--calibrate] [--out docs/search-eval.md]
"""

import argparse
import json
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://price-tracker.gavaller.com/api/tesco"
MODES = ("text", "semantic", "hybrid")
USER_AGENT = "price-tracker-search-eval/1.0"
REQUEST_PAUSE_SECONDS = 1.0

# (kind, query, [patterns that must all match one offer]); kind: literal = the
# product word is in the name; intent = described by need, synonym or category.
QUERIES = [
    ("literal", "zabpehely", [r"zabpehely|zab ?pehely"]),
    ("literal", "tejföl", [r"tejföl"]),
    ("literal", "paradicsom", [r"paradicsom"]),
    ("literal", "pálinka", [r"pálinka"]),
    ("literal", "mosogatószer", [r"mosogató"]),
    ("literal", "kávékapszula", [r"kapszula"]),
    ("literal", "zöld tea", [r"zöld ?tea|green tea"]),
    ("literal", "koffeinmentes kávé", [r"koffeinmentes|decaf"]),
    ("literal", "laktózmentes tej", [r"laktózmentes"]),
    ("literal", "kutyaeledel", [r"kutya|dog"]),
    ("typo", "csokolade", [r"csokolád|csoki"]),
    ("typo", "mosopor", [r"mosópor|mosószer|mosógél|mosókapszula"]),
    ("english", "orange juice", [r"narancs", r"lé\b|juice|ital|nektár"]),
    ("english", "toilet paper", [r"toalettpapír|wc-papír|wc papír"]),
    ("intent", "üdítő", [r"cola|üdítő|szörp|limonádé|tonic|szénsavas|ice tea|jeges tea|energiaital|gyümölcsital"]),
    ("intent", "reggelire gabonapehely", [r"müzli|pehely|granola|gabona"]),
    ("intent", "gluténmentes kenyér", [r"gluténmentes", r"kenyér|zsemle|pékáru|kifli|bagett|toast|szelet|cipó"]),
    ("intent", "babapelenka", [r"pelenka|nadrágpelenka"]),
    ("intent", "macskaalom", [r"alom"]),
    ("intent", "fogkrém gyerekeknek", [r"fogkrém|fogzselé", r"gyerek|kids|junior|baby|baba|\d-\d+ év"]),
    ("intent", "mosószer színes ruhákhoz", [r"mosó", r"color|szín"]),
    ("intent", "sörkorcsolya", [r"chips|pogácsa|mogyoró|perec|ropi|snack|kréker|pisztácia|tallér|rágcsa|popcorn"]),
    ("intent", "grillezni való hús", [r"grill|kolbász|tarja|csirkecomb|oldalas|sertés|marha|pácolt|bbq|steak"]),
    ("intent", "energiaital", [r"energia|energy|red bull|monster|hell|burn|xixo"]),
    ("intent", "cukormentes üdítő", [r"zero|cukormentes|light|diet|hozzáadott cukor nélkül"]),
    ("intent", "kenyérre kenhető", [r"vaj|margarin|krém|pástétom|lekvár|dzsem|méz|körözött|kence|hummusz|májkrém"]),
    ("intent", "fehérjeszelet sportolóknak", [r"protein|fehérje"]),
    ("intent", "olasz tészta", [r"spagetti|penne|fusilli|tészta|tagliatelle|lasagne|farfalle|makaróni|linguine"]),
    ("intent", "halkonzerv", [r"tonhal|szardínia|makréla|hering|lazac|hal"]),
    ("intent", "fürdőszoba tisztító", [r"fürdő|vízkő|wc|penész|zuhany|csaptelep|tisztító"]),
]
NONSENSE = ["xqzvbt", "autógumi téli", "repülőjegy budapest london", "laptop töltő 65w"]


last_latency_ms = 0.0


def fetch(base: str, query: str, stores: str, mode: str, limit: int = 10, min_score=None) -> dict:
    params = {"q": query, "limit": limit, "mode": mode}
    if stores:
        params["stores"] = stores
    if min_score is not None:
        params["min_score"] = min_score
    # Cloudflare answers the default urllib agent with 403, so identify the script.
    request = urllib.request.Request(f"{base}/search?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            time.sleep(REQUEST_PAUSE_SECONDS)  # the public edge rate-limits bursts with 429
            global last_latency_ms
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
            last_latency_ms = (time.perf_counter() - started) * 1000
            return body
        except OSError:
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))


def is_relevant(row: dict, patterns: list) -> bool:
    for offer in row["offers"]:
        text = " ".join([offer.get("name") or ""] + [c for c in offer.get("category_path") or [] if c]).lower()
        if all(re.search(pattern, text) for pattern in patterns):
            return True
    return False


def score(rows: list, patterns: list) -> tuple:
    flags = [is_relevant(row, patterns) for row in rows[:10]]
    precision = sum(flags) / 10
    rank = next((i + 1 for i, flag in enumerate(flags) if flag), None)
    return precision, (1 / rank if rank else 0.0)


def evaluate(base: str, stores: str, min_score=None) -> dict:
    results = {}
    for mode in MODES:
        per_query = []
        latencies = []
        answered_modes = set()
        for kind, query, patterns in QUERIES:
            page = fetch(base, query, stores, mode, min_score=min_score)
            latencies.append(last_latency_ms)
            answered_modes.add(page.get("mode", mode))
            precision, rr = score(page["results"], patterns)
            per_query.append({"kind": kind, "query": query, "p10": precision, "rr": rr, "n": len(page["results"])})
        results[mode] = {"queries": per_query, "latency_ms": statistics.median(latencies), "answered": sorted(answered_modes)}
    return results


def calibrate(base: str, stores: str, thresholds: list) -> list:
    rows = []
    for threshold in thresholds:
        precisions = []
        for _, query, patterns in QUERIES:
            precisions.append(score(fetch(base, query, stores, "semantic", min_score=threshold)["results"], patterns)[0])
        nonsense = [len(fetch(base, q, stores, "semantic", min_score=threshold)["results"]) for q in NONSENSE]
        rows.append({"threshold": threshold, "p10": statistics.mean(precisions), "nonsense_results": sum(nonsense)})
    return rows


def markdown(results: dict, calibration: list, stores: str, min_score=None) -> str:
    kinds = sorted({q["kind"] for q in results["text"]["queries"]})
    lines = [
        f"Stores: {stores or 'all enabled'}; {len(QUERIES)} queries; top 10 rows per query"
        + (f"; similarity threshold {min_score}." if min_score is not None else "."),
        "",
        "| Mode | P@10 | MRR | Zero results | Median latency |" + "".join(f" P@10 {k} |" for k in kinds),
        "|---|---|---|---|---|" + "---|" * len(kinds),
    ]
    for mode in MODES:
        queries = results[mode]["queries"]
        by_kind = {k: statistics.mean(q["p10"] for q in queries if q["kind"] == k) for k in kinds}
        lines.append(
            f"| {mode} | {statistics.mean(q['p10'] for q in queries):.2f} | {statistics.mean(q['rr'] for q in queries):.2f} "
            f"| {sum(1 for q in queries if q['n'] == 0)} | {results[mode]['latency_ms']:.0f} ms |"
            + "".join(f" {by_kind[k]:.2f} |" for k in kinds)
        )
    lines += ["", "| Query | Kind | " + " | ".join(f"{m} P@10 / RR" for m in MODES) + " |", "|---|---|" + "---|" * len(MODES)]
    for index, (kind, query, _) in enumerate(QUERIES):
        cells = [f"{results[m]['queries'][index]['p10']:.1f} / {results[m]['queries'][index]['rr']:.2f}" for m in MODES]
        lines.append(f"| {query} | {kind} | " + " | ".join(cells) + " |")
    if calibration:
        lines += ["", "| Semantic threshold | P@10 (semantic) | Results for 4 nonsense queries |", "|---|---|---|"]
        lines += [f"| {row['threshold']:.2f} | {row['p10']:.2f} | {row['nonsense_results']} |" for row in calibration]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--stores", default="")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--min-score", type=float, default=None,
                        help="similarity threshold to measure with (default: the deployed SEMANTIC_MIN_SCORE)")
    parser.add_argument("--out")
    args = parser.parse_args()

    results = evaluate(args.base, args.stores, args.min_score)
    calibration = calibrate(args.base, args.stores, [0.0, 0.78, 0.8, 0.82, 0.84, 0.86]) if args.calibrate else []
    report = markdown(results, calibration, args.stores, args.min_score)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(report)
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
