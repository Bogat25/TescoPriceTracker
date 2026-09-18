# Adding a store

The system claims to be store-neutral. This is the recipe that backs the claim,
with Auchan as the worked example — it was added to a Tesco-only codebase, and
these are the pieces that were needed.

Read [architecture.md](architecture.md) first for the offer shape and the
identifiers.

---

## 1. What a store needs before you start

A store is a candidate only if all four hold. [store-spike.md](store-spike.md)
records why Penny, Lidl, SPAR and Kifli did not make it.

1. **A listing source** that returns the whole range, not just this week's
   leaflet — an API or a paginated category tree.
2. **Stable product IDs**, so a product keeps its identity and its history
   between runs.
3. **Barcodes**, or the products cannot be linked to any other store and the
   comparison has nothing to compare.
4. **Prices in the listing**, including the promotional and loyalty price if
   the shop has one, without logging in.

Check the shop's `robots.txt` and terms before writing any client. Kifli is
excluded because its `robots.txt` refuses automated agents.

---

## 2. The pieces

Auchan lives in `stores/auchan/`. A new store is the same five files plus the
registrations.

### 2.1 Client — `stores/auchan/client.py`

Only HTTP: paging, timeouts, retries, rate limiting, and turning the shop's
failures into two exceptions the crawler understands — one retryable
(`AuchanUnavailable`, HTTP 5xx and 429) and one not (`AuchanContractError`, a
response that is not shaped as agreed). Pace the requests; a scrape is not an
emergency.

### 2.2 Mapper — `stores/auchan/mapper.py`

The shop's JSON to the stored document, and the stored document to an
**offer**. This is the only file allowed to know the shop's field names.

Everything store-specific belongs here: how the pack size is expressed, what
counts as a promotion, whether loose goods are priced per kilo, how the product
URL is built. Auchan's card price, for example, is only published as a *unit*
price, so the shelf price is reconstructed and the rounding route with the
smaller error is chosen ([ADR 4](adr/0004-auchan-card-prices.md)).

### 2.3 Repository — `stores/auchan/repository.py`

MongoDB for this store's collection and run state: indexes, writing a crawled
page into today's history entry, the run state, and marking what still needs
details or re-vectorising. Keep the daily history merge idempotent — a second
pass on the same day must replace that day, not append to it.

### 2.4 Adapter — `stores/auchan/adapter.py`

The read interface every store must implement. The shared query layer calls
only these:

| Method | Returns |
|---|---|
| `search(query, limit, category_query=None)` | `{results: [offer], total}` |
| `browse(limit, sort_by, sort_dir, category_query=None)` | `{results: [offer], total}` |
| `find_by_ids(ids)` | offers, in the given order |
| `find_by_gtins(gtin_norms)` | offers — this is what links stores |
| `get_offer(store_product_id)` | one offer, with description and ingredients |
| `get_history(store_product_id)` | `[{date, regular, promo, loyalty, ...}]` |
| `iter_histories(gtin_norms=None)` | `(ref, name, category, gtin_norm, rows)` for statistics |
| `iter_categories()` | `(gtin_norm, category_path)` for the category mapping |

`category_query` is a Mongo fragment built by `stores.categories`; merge it
into the query with `stores.browse.narrow` so neither clause loses an operator.

### 2.5 Crawler — `stores/auchan/crawler.py`

The daily run: resume an unfinished day, walk the categories, save each page,
then publish (statistics, category mapping, price-drop alerts). Keep every
stage separately recorded in the run state, so a retry repeats only what is
unfinished.

---

## 3. Registering it

1. **Registry** — add a `StoreConfig` to `DEFAULT_STORES` in
   `stores/registry.py`: id, display name, the three switches, display order,
   website. The id must match `^[a-z][a-z0-9_-]{1,31}$`; it becomes part of
   every `ref`.
2. **Adapter table** — add it to `ADAPTERS` in `stores/queries.py`.
3. **Embedding text** — add its fields to `stores/embedding_text.py`, so the
   vectors describe the product the same way for every store.
4. **Vectorising** — add the store to `stores/vectorize.py` (which documents
   feed the text, and which field is the category payload).
5. **Alert feed** — add it to `stores/alerts_feed.py`, so price drops in the
   new store reach the alert service.
6. **Scheduler** — a scheduler entry point and a container in
   `docker-compose.yml`, modelled on `auchan-scheduler`.
7. **Grafana** — scrape-completion and error rules for the new service, in the
   Observability repository.
8. **Tests** — client, mapper, crawler and adapter unit tests, plus a seeded
   catalogue in `tests/integration/conftest.py` so the two-store integration
   tests become three-store ones.

The frontend needs nothing: it reads the store list from `/api/prices/stores`
and colours the chips from the registry order.

---

## 4. The switches

Three flags per store, in the `stores` collection, changed without a redeploy
([ADR 3](adr/0003-store-switches-in-the-database.md)):

| Flag | Off means |
|---|---|
| `enabled` | The store does not exist for visitors: no search results, no product pages, no alerts, no statistics. Asking for it by name is a 404 |
| `scrape_enabled` | The scheduler collects no prices. What was collected stays visible |
| `loyalty_enabled` | The loyalty-price reader does not run |

```bash
docker compose exec api python -m stores.admin list
docker compose exec api python -m stores.admin set auchan enabled=false
```

A change reaches every service within the registry cache time, 60 seconds.
There is no HTTP endpoint for this on purpose — the public gateway forwards
`/api/v1`.

Disabling Tesco also closes the legacy Tesco-only routes (`/api/*/products`,
`/api/*/stats`, `/api/*/recommendations`), which predate the store layer.

---

## 5. What must not leak

The point of the layer is that only `stores/<store>/` knows the store. When
something store-specific appears above it, the next store pays for it.

- No store id in `stores/queries.py` beyond the `ADAPTERS` table.
- No store-specific field name outside the mapper — the neutral names are
  `regular`, `promo`, `loyalty`.
- No assumption that a store has every product, a barcode, a promotion, a
  loyalty price, or a category tree of any particular depth.
- No store-specific ordering: rows merge by rank, offers sort by price.

---

## 6. Categories

Each shop has its own category tree, so one vocabulary is learned rather than
configured. Tesco's two top levels are canonical; another store's paths are
mapped onto them using the products both stores sell, one vote per barcode-linked
pair. A path is mapped only when at least 3 linked products agree and at least
60 % of them agree; a path nothing agrees on is left unmapped rather than
guessed, and the build reports the coverage.

```bash
docker compose exec api python -m stores.admin categories
```

The daily scrape rebuilds it as part of publishing. A new store needs no
configuration here — give it `iter_categories()` and enough shared products,
and its categories map themselves. A store with few shared products will map
little, which the coverage figures make visible instead of hiding.

---

## 7. Checklist

```
[ ] robots.txt and terms permit collection
[ ] client:      paging, pacing, retryable vs contract errors
[ ] mapper:      document + offer, prices incl. promo and loyalty, URL
[ ] repository:  indexes, idempotent daily history, run state
[ ] adapter:     the eight methods above
[ ] crawler:     resumable stages, publish at the end
[ ] registry:    StoreConfig entry with sensible switch defaults
[ ] queries:     ADAPTERS entry
[ ] search:      embedding_text + vectorize entries
[ ] alerts:      alerts_feed entry
[ ] scheduler:   entry point + compose service
[ ] grafana:     scrape completion and error rules
[ ] tests:       unit tests + a seeded store in the integration fixtures
[ ] docs:        a line in architecture.md, a note in store-spike.md
```
