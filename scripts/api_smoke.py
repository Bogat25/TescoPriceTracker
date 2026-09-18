"""Smoke-check a deployed price tracker: every public endpoint, in both routes.

Run it after a deploy. Each check states what it expects, so a failure says
what broke rather than only that something did. Anonymous only: endpoints that
need a signed-in user are checked for *refusing* anonymous access, which is the
part that can be verified without a browser.

    python scripts/api_smoke.py [--base https://price-tracker.gavaller.com] [--route /api/prices]
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "price-tracker-smoke/1.0"   # the edge answers the default agent with 403
PAUSE_SECONDS = 0.6                       # the edge rate-limits bursts


class Result:
    def __init__(self):
        self.checks = []

    def record(self, name, ok, detail=""):
        self.checks.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
        return ok

    @property
    def failed(self):
        return [name for name, ok, _ in self.checks if not ok]


def get(url, timeout=30):
    """Return (status, body) without raising for HTTP error codes."""
    time.sleep(PAUSE_SECONDS)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except Exception:
            return exc.code, None
    except OSError as exc:
        return 0, {"error": str(exc)}


def api(base, route, path, **params):
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return get(f"{base}{route}{path}{query}")


def run(base, route, result):
    status, stores = api(base, route, "/stores")
    store_ids = [s["id"] for s in (stores or {}).get("stores", [])]
    result.record("store list", status == 200 and store_ids, f"stores: {', '.join(store_ids) or 'none'}")

    status, page = api(base, route, "/search", q="tej", limit=5)
    rows = (page or {}).get("results", [])
    result.record("hybrid search returns rows", status == 200 and len(rows) > 0,
                  f"mode={(page or {}).get('mode')} rows={len(rows)}")
    result.record("search rows carry a price per store",
                  bool(rows) and all(row.get("offers") for row in rows),
                  f"first row stores: {[o['store'] for o in rows[0]['offers']] if rows else []}")

    status, page = api(base, route, "/search", q="gluténmentes kenyér", limit=10)
    names = " ".join((row.get("name") or "").lower() for row in (page or {}).get("results", []))
    result.record("meaning-based search finds gluten-free bread",
                  status == 200 and "gluténmentes" in names)

    status, text_page = api(base, route, "/search", q="tej", limit=5, mode="text")
    result.record("text mode still answers", status == 200 and text_page.get("mode") == "text")

    for store in store_ids:
        status, page = api(base, route, "/search", q="tej", limit=3, stores=store)
        offers = [o["store"] for row in (page or {}).get("results", []) for o in row["offers"]]
        result.record(f"store filter: {store}", status == 200 and set(offers) <= {store},
                      f"{len(offers)} offers")

    status, page = api(base, route, "/browse", limit=5, sort_by="discount", sort_dir="desc")
    result.record("browse by discount", status == 200 and len((page or {}).get("results", [])) > 0)

    # A linked product: search results carry group IDs for barcode-linked rows.
    status, page = api(base, route, "/search", q="coca-cola", limit=20)
    group = next((row["group_id"] for row in (page or {}).get("results", []) if row.get("group_id")), None)
    if group:
        status, row = api(base, route, f"/groups/{urllib.parse.quote(group)}")
        result.record("group page", status == 200 and row.get("offers"),
                      f"{group} in {len(row.get('offers', []))} store(s)")
        status, history = api(base, route, f"/groups/{urllib.parse.quote(group)}/history")
        result.record("group price history", status == 200 and history.get("series"))
        status, similar = api(base, route, f"/groups/{urllib.parse.quote(group)}/similar", limit=5)
        result.record("similar products", status == 200 and similar.get("results"),
                      f"{len(similar.get('results', []))} rows")
        ref = row["offers"][0]["ref"]
        status, offer = api(base, route, f"/offers/{urllib.parse.quote(ref)}")
        result.record("single offer", status == 200 and offer.get("ref") == ref)
    else:
        result.record("group page", False, "no linked product in the search results")

    status, insights = api(base, route, "/insights")
    result.record("per-store statistics", status == 200 and insights.get("by_store"))
    status, comparison = api(base, route, "/insights/compare")
    result.record("store comparison statistics", status == 200 and comparison is not None)

    status, cold = api(base, route, "/recommended/cold", limit=5)
    result.record("recommendations (anonymous)", status == 200 and cold.get("results"),
                  f"type={cold.get('type')}")
    status, _ = api(base, route, "/recommended/personalized", limit=5)
    result.record("personal recommendations need a login", status == 401, f"HTTP {status}")

    status, _ = get(f"{base}/api/alerts/")
    result.record("alerts need a login", status == 401, f"HTTP {status}")

    # The browser extension is pinned to the old route and endpoints.
    status, legacy = get(f"{base}/api/tesco/products/search?q=tej&limit=3")
    result.record("extension route still answers", status == 200 and legacy is not None)
    status, health = get(f"{base}/api/tesco/health")
    result.record("api health", status == 200, str(health))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="https://price-tracker.gavaller.com")
    parser.add_argument("--route", default="/api/prices", help="catalogue route prefix to test")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    result = Result()
    print(f"Checking {args.base}{args.route}\n")
    run(args.base.rstrip("/"), args.route.rstrip("/"), result)
    print(f"\n{len(result.checks) - len(result.failed)}/{len(result.checks)} checks passed")
    if result.failed:
        print("failed: " + ", ".join(result.failed))
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
