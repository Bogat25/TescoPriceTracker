# Price tracker: upgrade plan (multi-store, store-neutral)

Status: **Done. Phases 0–8 deployed (2026-09-17), phase 9 finished
(2026-09-18); the phase 9 work is committed but not yet pushed.**
Background: [store-spike.md](store-spike.md). Security model:
[security.md](security.md). Search: [semantic-search.md](semantic-search.md).

This plan turns the Tesco Price Tracker into a **store-neutral** price tracker.
Tesco and Auchan are equal stores, and each can be switched off without a
redeploy. It also covers the BSc thesis gaps (several webshops, semantic
search, tests, security, documentation). Each numbered step can be committed on
its own.

---

## 1. Overview

| Phase | Content | Status |
|---|---|---|
| 0 | Quick fixes, recommendation tests in CI | ✅ Done |
| 1 | Store registry, switches, store-neutral API (read side) | ✅ Done |
| 2 | Auchan crawl, `auchan-scheduler`, alert rules | ✅ Done |
| 3 | Barcode linking, merged product rows, compare, cross-store stats, loyalty-price check | ✅ Done |
| 4 | Store-aware frontend (selector, badges, compare table); users see Auchan | ✅ Done |
| 5 | Store-aware alerts and recommendations | ✅ Done |
| 6 | Semantic and hybrid search across stores (incl. Auchan vectors) | ✅ Done |
| 7 | Neutral name and routes | ✅ Done |
| 8 | Security hardening | ✅ Done |
| 9 | Tests (cross-cutting), category mapping and documentation | ✅ Done |

**Auchan card prices (decided, D3 = accept and label):** anonymous responses contain the
card unit price only for products flagged with a card offer (~380), and those
prices match GVH Árfigyelő. Árfigyelő also shows card prices (mostly a flat
30 % off) for products with no anonymous card data, most likely the ~1,250
card offers listed in category 14288, which is empty for anonymous visitors.
The logged-in reader is not built; the comparison page says so. See §2.1.

---

## 2. Decisions

### 2.1 Made

| Topic | Decision |
|---|---|
| Second store | **Auchan** (auchan.hu online shop). Penny, Lidl, SPAR, Kifli.hu rejected; see store-spike.md §7 |
| Neutrality | No store is special. Tesco and Auchan are both registry entries and can each be disabled for users |
| Naming | **Price Tracker** (D1, 2026-09-17). The hostname `price-tracker.gavaller.com` was already store-neutral and stays; the API route becomes `/api/prices/*` with `/api/tesco/*` kept as a working alias |
| Default view | **One product row with a price per enabled store.** Barcode-linked products appear once; unlinked and own-brand products appear as single-store rows |
| Alerts | **The user picks stores per alert** (default: all enabled). Fires when any selected store meets the condition. Alerts on disabled stores are paused, not deleted |
| Order | Stores first, then search. Semantic search is built store-aware from the start. Frontend before alerts (revised 2026-09-17) |
| Storage | Separate collections per store; shared layers only join when a query needs it. The Tesco collection is not migrated |
| Loyalty prices | A `loyalty` price channel for every store. Tesco: Clubcard price. Auchan: card price derived from the anonymous card unit price (flagged offers only; see D3) |
| Store switches | Changed with `python -m stores.admin` in the `api` container; no HTTP endpoint, because the gateway forwards every `/api/v1/*` path |
| Git | Commit directly on each repository's default branch; the owner's push releases |
| Auchan card prices | **(a) Accept partial coverage and label it** (D3, 2026-09-17). The comparison page already says card prices are known for part of Auchan's offers. The logged-in reader is not built: it would need the burner account's credentials in the stack, Auchan's terms are not clearly permissive, and card prices may depend on the account's loyalty level, so the data would be one account's view rather than everyone's |

### 2.2 Open

None. D1 (name and routes) and D2 (host CPU) and D3 (Auchan card prices) were
all decided on 2026-09-17; see §2.1.

---

## 3. Architecture

```
                         stores registry (Mongo `stores`)
            { _id, name, enabled, scrape_enabled, loyalty_enabled, order, website }
                                       │
   ┌───────────────────────────┬───────┴───────────────────────┐
   │ products  (Tesco, as-is)  │  auchan_products              │   one collection per store,
   │ runs      (Tesco, as-is)  │  auchan_runs                  │   store-specific fields kept
   └─────────────┬─────────────┴──────────────┬────────────────┘
                 │   per-store adapters → common `Offer` model │
                 └───────────────┬─────────────────────────────┘
                                 │
          product groups (Phase 3): group_id = "g:{gtin_norm}",
          resolved through the indexed gtin_norm field of every store collection
                                 │
     API: stores · search · browse · offers · groups · compare · stats · alerts · recommendations
          ?stores=a,b   (default: all enabled stores; single store → no join)
```

### 3.1 Identifiers

| Thing | Format | Example |
|---|---|---|
| Store ID | lowercase slug | `tesco`, `auchan` |
| Offer reference (one listing in one store) | `{store}:{store_product_id}` | `tesco:121262922`, `auchan:678170` |
| Product group (linked by barcode) | `g:{gtin_norm}` | `g:54026193` |
| Normalised GTIN | digits, leading zeros stripped, at least 7 digits | `00000054026193` → `54026193` |
| Qdrant point ID (collection `offers`) | `uuid5(namespace, ref)` | `uuid5(…, "tesco:121262922")` |

In-store codes (EAN-13 starting with `2`, e.g. weighed products) are flagged
`is_weighed` and never linked across stores.

### 3.2 `Offer` model (implemented)

`store`, `ref`, `store_product_id`, `gtin`, `group_id`, `is_weighed`, `name`, `brand`,
`image_url`, `category_path[]`, `pack_size`, `pack_unit`, `availability`,
`prices {regular, promo, loyalty, unit_price, unit}`, `effective_price`,
`discount_ratio`, `price_date`, `flags[]`, `url`.

History rows: `{date, regular, promo, loyalty, unit_price, unit, availability}`.
Tesco's stored `normal`/`discount`/`clubcard` are mapped on read.

### 3.3 Store switches (implemented)

| Switch | Effect when `false` |
|---|---|
| `enabled` | Store hidden from store-neutral endpoints; `?stores=` naming it returns 404; for Tesco also the legacy `/products`, `/stats`, `/recommendations`, `/{tpnc}.json` endpoints return 404. Data is kept |
| `scrape_enabled` | The store's scheduler skips collection and logs `scrape.disabled` once a day (alert rules treat it as healthy) |
| `loyalty_enabled` | Reserved; unused now that loyalty prices come from the normal crawl |

Registry reads are cached for 60 s and fall back to the defaults if MongoDB is
unavailable.

---

## 4. Done

### 4.1 Phase 0: quick fixes

- API-key prefix no longer logged; vector-sync token compared in constant time.
- Recommendation tests were git-ignored; now tracked, rewritten against the
  current engine, and part of `pytest` `testpaths`.
- Tesco `deposit_amount` gap explained (metadata only written on a product's
  first fetch; field added later). Fix deferred: it needs extra Tesco requests.

### 4.2 Phase 1: store layer

- `stores` package: `ids`, `registry`, `offers`, `tesco` and `auchan` adapters,
  `queries` (merging), `admin` CLI.
- Endpoints (public through `/api/tesco/*` until Phase 7):
  `GET /api/v1/stores`, `/search?q=&stores=&skip=&limit=`,
  `/browse?stores=&sort_by=name|price|discount&sort_dir=`,
  `/offers/{ref}`, `/offers/{ref}/history`.
- Several stores are merged without favouring any: search results interleave
  by rank per store; browse results merge by the sort key.
- `gtin_norm` on Tesco products (written by the scraper, backfilled at start).

### 4.3 Phase 2: Auchan ingestion

- Client: anonymous token (`/fe-api/get-token`), 1 request/s, retries with
  `Retry-After`, outage vs contract errors.
- Daily crawl of 8 grocery categories into `auchan_products`, resumable per
  page from `auchan_runs`; ~15k products in ~8 min.
- Prices: regular, promo, **card price = `loyaltyUnitPrice` (discounted) ×
  pack size** (per-kg price for loose items), unit price, availability,
  promo/card validity dates, flags, own-brand marker.
- Description and ingredients fetched for new or renamed products (300/run).
- `auchan-scheduler` service (cron `30 6 * * *`), health check, Grafana rules
  `auchan-scrape-incomplete|fatal|upstream-failure-burst|stale`.

### 4.4 Deployment 2026-09-17

Observability and tesco-price-tracker redeployed. After the deploy: no error
events for any tracker service, new endpoints answer in 0.1–0.5 s, Auchan
products searchable within minutes, legacy Tesco endpoints unchanged.

---

## 5. Phase 3: linking and shared queries (implemented 2026-09-17)

1. **Group key = normalised barcode.** Every offer carries
   `group_id = "g:{gtin_norm}"` (none for in-store codes or missing barcodes).
   Instead of a synchronised `product_groups` collection, groups are resolved
   through the indexed `gtin_norm` field of each store collection: nothing to
   keep in sync, never stale. Duplicate barcodes inside one store stay in the
   same group.
2. **Rows.** `/search` and `/browse` return rows for any store selection:
   `{group_id, gtin, name, brand, image_url, best_price, cheapest_stores,
   store_count, offers[]}`, offers cheapest first; display name and image
   follow registry order so they do not flip with prices. Offers of a linked
   product missing from another requested store's result window are filled in
   by barcode. `total` counts offers (`total_counts_offers: true`).
3. **Groups.** `GET /api/v1/groups/{group_id}?stores=` (row with every
   selected store's offer) and `/groups/{group_id}/history?stores=` (a price
   series per offer).
4. **Statistics** under `/api/v1/insights` (the legacy Tesco `/stats/*`
   endpoints stay unchanged until the frontend moves in Phase 4):
   - `GET /insights?stores=`: per store price index, product counts, price
     tiers, price channels (regular/promo/card), best shopping day, discounts
     by weekday, volatility, global average, 30-day inflation. One pass per
     store, cached per day, rebuilt after that store's scrape.
   - `GET /insights/top-discounts` and `/insights/price-drops`: merged across
     stores with `store` and `ref`.
   - `GET /insights/compare?stores=` (two or more stores): linked products
     priced in the last two days; cheapest counts by regular and by best
     price, ties, average price index vs the cheapest store (overall and per
     category of the first store), and a daily basket total over the last 60
     days. Cached for an hour; dropped when a store's statistics are rebuilt.
5. **Card-price validation** against GVH Árfigyelő (Auchan `LOYALTY`, 106
   barcodes, 41 in the crawl): where Auchan sends a card unit price, 4 of 5
   match exactly after choosing the more precise rounding route; the fifth
   disagrees inside Árfigyelő itself. For 36 products Árfigyelő has a card
   price (mostly 30 % off) that anonymous data does not show. Comparisons
   therefore report regular and best prices separately; see D3.
6. **Tests:** grouping (in-store codes and missing barcodes never grouped),
   filling missing stores, row ordering, group lookups, per-store statistics,
   comparison, cache expiry and rebuild.

---

## 6. Phase 4: store-aware frontend (implemented 2026-09-17)

Deployed result of Phase 3 (2026-09-17): 6,221 linked Tesco–Auchan products;
cheapest by regular price Tesco 2,981, Auchan 1,720, ties 1,520; average price
index vs the cheapest store Tesco 102.75, Auchan 107.73.

1. **Stores.** `StoresService` loads `GET /stores`; the visitor's selection is
   remembered in localStorage and sent as `stores` (empty = every enabled
   store, so a newly enabled store appears automatically). The store chips
   (`app-store-selector`) are hidden when only one store is enabled.
2. **Search** uses `/search` rows: live suggestions and result cards
   (`app-product-row-card`) show one price line per store, cheapest
   highlighted, promo and card prices marked. Pages are capped at the API's
   first 1,000 results.
3. **Catalogue** uses `/browse` (sort by name, price or discount) and `/search`
   (relevance), one table row per product with every store's price. The Tesco
   category pills and rating sort are gone: the two stores' category trees do
   not match (see Phase 9 follow-up).
4. **Product pages.** `/p/:groupId` (linked product) and `/o/:ref` (single
   offer): comparison table (regular, promo, card, unit price, availability,
   date, links to the store and to the rich Tesco page), a history chart with
   one line per store (lowest price per day), description and ingredients.
   The rich Tesco page `/products/:tpnc` shows a "price in other stores" panel
   when the product is linked. Links: linked rows open `/p/`, Tesco-only rows
   the Tesco page, other stores `/o/`.
5. **Statistics** read `/insights` through the existing service shapes (store
   tabs; the Tesco "product analysis" tab is unchanged) and add a "Compare
   stores" tab from `/insights/compare`. Price-drop links follow the store.
   Backend fix: 30-day inflation and promo/card savings now compare the same
   products (Tesco showed +25.7 % inflation from comparing different product
   sets).
6. `/offers/{ref}` returns `description` and `ingredients`.
7. Translations (hu/en) for all new labels; search texts no longer name Tesco.
8. Tests: store selection and persistence, row links, best-price kind, chart
   series alignment, catalogue API parameters, statistics mapping (14 specs).

Not in this phase: legacy `/stats/*` endpoints stay until nothing calls them;
home page texts still name Tesco (Phase 7).

---

## 7. Phase 5: store-aware alerts and recommendations (implemented 2026-09-17)

1. **Alert model.** `target` is an offer ref (`auchan:678170`) or a group ID
   (`g:5998…`), and `stores` lists the watched stores. An offer alert watches
   its own store. A group alert watches the stores the user ticked (all enabled
   stores when none are sent). `productId` stays the bare tpnc on Tesco alerts,
   because the browser extension matches on it. Other alerts store the target
   there. The API still accepts `{productId: tpnc}`.
2. **Migration** runs at alert-service startup and is idempotent: alerts
   without `target` get `tesco:{productId}` and `["tesco"]`
   (`alerts.migrated` log). New index `target_enabled`.
3. **Producers.** The Tesco scraper sends drops as `tesco:{tpnc}` with the
   group ID (`runKey` stays `daily:{date}`). The Auchan crawl has a publish
   stage: it rebuilds statistics, then sends today's drops (best of the regular,
   promo and card prices vs the previous day, at most 7 days back) with
   `runKey` = `auchan:{date}`. A day counts as finished only when the alerts are
   delivered. Otherwise the next pass retries publishing without crawling
   again.
4. **Evaluator** matches drops by ref and by group, only for watched and
   enabled stores. Alerts whose watched stores are all disabled show as
   `paused`. The digest email has a Store column and neutral wording.
5. **Frontend.** The comparison page has an alert form with store chips
   (lowest price of the ticked stores is the base). The alerts page and the
   home panel resolve names, prices and links for all three target kinds, and
   show the watched stores and a "paused" badge.
6. **Recommendations.** `GET /recommended/cold|personalized?stores=` returns
   product rows. Personal picks still come from the Tesco vectors: group and
   Auchan alerts count through the Tesco product with the same barcode. Each
   pick shows the selected stores' prices, and the remaining slots are the
   biggest discounts across the selected stores (de-duplicated by group).
   The path is outside `/recommendations`, so it keeps working while Tesco is
   disabled (then there are only deals). The old endpoints stay for the
   extension.
7. **Observability:** `auchan-publication-failed` rule (latest of
   `scrape.finalization_failed` / `scrape.published`).
8. **Tests:** target normalisation, store resolution, group alerts per store,
   disabled and unwatched stores, legacy alerts, migration idempotency, the
   Auchan drop feed and publish retry, recommendation rows per store
   selection, alert-target mapping for the engine, and the alert form request
   builder.

Moved to Phase 6: Qdrant payload with `store`/`ref`/`gtin_norm` and Auchan
vectors, so Auchan-only products can be recommended personally.

---

## 8. Phase 6: semantic and hybrid search (implemented 2026-09-17)

Full technical description: [semantic-search.md](semantic-search.md).
Host decision (D2): Intel Core i5-12500, `linux/amd64`.

1. **`embedding-service`** (new image `tesco-tracker-embedding`): FastAPI and
   sentence-transformers on CPU-only PyTorch, `intfloat/multilingual-e5-small`
   baked in at a pinned revision, `POST /embed {texts, mode: query|passage}`
   (the service adds the E5 prefixes). Internal network only, limited to 4 CPUs
   and 1.5 GB. It logs its measured throughput at start-up. Measured: 172
   passages/s on 4 CPUs, 7–8 ms per query, 707 MiB.
2. **`vectorizer`** (backend image, `python -m stores.vectorize`) replaces the
   laptop worker. Every 30 minutes it embeds new or changed products of every
   enabled store (content hash per product in `embedding_state`, model identity
   included), upserts them into the Qdrant collection `offers` (one point per
   offer ref, payload `store`/`ref`/`group_id`/`gtin_norm`/`category`) and
   removes points of products that left a catalogue.
3. **`/search?mode=hybrid|semantic|text`** (default `hybrid`): per store, the
   text index and Qdrant (filtered by store, similarity threshold) are fused
   with Reciprocal Rank Fusion (k = 60). Stores are interleaved by rank and
   results grouped by barcode as before. Barcodes use text only. If vectors
   are unavailable the answer is text search (`mode: "text"`,
   `search.semantic_unavailable`). Live suggestions use `mode=text`.
4. **Similar products:** `/groups/{id}/similar` and `/offers/{ref}/similar`
   exclude the product's own group. Shown on the comparison page.
5. **Recommendation engine** reads the `offers` collection (Tesco points,
   `store = tesco` filter). The old `products` collection and the laptop sync
   API stay until the Phase 9 clean-up.
6. **Evaluation:** `scripts/search_eval.py` (30 Hungarian queries: literal,
   intent, typo and English; precision@10, MRR, latency) and threshold
   calibration. Results in [search-eval.md](search-eval.md).
7. **Observability:** `vectorizer-failing`, `vectorizer-stale` and
   `semantic-search-degraded` rules.
8. **Tests:** RRF, per-store hybrid ranking, fallback, barcode queries,
   similar products, incremental vectorizing (unchanged, changed, model change,
   removal, batching), embedding texts, the embedding-service API.

Not done: embedding + brand + pack-size linking without barcodes (optional).
Cross-store personal recommendations were done on 2026-09-18, once the category
mapping existed (Phase 10).

---

## 9. Phase 7: neutral name and routes (implemented 2026-09-17)

D1: the site is **Price Tracker**; the hostname stays, the API route becomes
`/api/prices/*`.

1. **Site name** in the navbar, sidebar, page titles, meta and JSON-LD, the
   footer, the privacy policy and both translations. No store is named in
   site-wide text; "Tesco" now appears only where it means the store (the
   extension section, the data-source list, per-offer links).
2. **`/api/prices/*`** added to the YARP gateway and to the frontend's nginx,
   both rewriting to the API's `/api/v1/*`. `/api/tesco/*` keeps working for
   the browser extension and bookmarks.
3. **Frontend config**: `apiBaseUrl` (default `/api/prices`) replaces
   `tescoApiBaseUrl`; the old runtime key is still read, so the deployed
   `TESCO_API_BASE_URL` value keeps working until it is switched to
   `/api/prices` through the controller.
4. **Gateway log classification** now recognises both prefixes and names the
   store-neutral endpoints (`row_search`, `row_browse`, `offer_view`,
   `group_view`, `insights`, `recommended_*`, `store_list`), so the dashboards
   stop filing them as generic requests.
5. **Grafana**: dashboards and alert rules moved from the folder
   "Tesco Price Tracker" to "Price Tracker".
6. **API title**: "Price Tracker API".

Not done, moved to Phase 9: the ClickHouse product dimension is still keyed by
`tpnc`. Making it `ref` + `store` touches RefDataSync, the ClickHouse
dictionary and two dashboards, and is independent of the rename. The Keycloak
realm keeps its `tesco-tracker` name: renaming a realm invalidates every
session and token for a cosmetic gain.

---

## 10. Phase 8: security hardening (implemented 2026-09-17)

Full write-up: [security.md](security.md).

1. **Per-service MongoDB accounts.** `svc_api`, `svc_scraper` and `svc_alerts`
   with rights on the databases they actually use, replacing the shared root
   account. `mongo/init-users.js` runs on every deploy in the one-shot
   `mongo-users` container and creates or updates them from Infisical
   passwords. A service without its own password keeps working and logs
   `mongo.root_credentials`, so a partial rollout is visible instead of broken.
2. **CORS allowlists** (`cors_policy.py`): the site's hostnames plus browser
   extension schemes, credentials only with a real allowlist, and a warning
   when a wildcard is configured. Replaces `allow_origins=["*"]` in the API and
   the alert service.
3. **mongo-express is off by default**; it starts only with
   `COMPOSE_PROFILES=admin-tools`, and stays tailnet-only with basic auth.
4. **Tesco rate limiting**: an adaptive pacer keeps a floor between requests,
   doubles it after every 429 (to a ceiling) and halves it back after a run of
   successes (`graphql.pace_changed`). The existing `Retry-After` handling and
   shared cooldown are unchanged; pacing is what keeps a pass from earning the
   penalty in the first place.
5. **Tesco metadata repair**: fields Tesco added after a product's first fetch
   (deposit amount and the rest) used to stay missing forever, because later
   days fetch prices only. Each pass now re-fetches a bounded number of
   products whose stored metadata is older than 30 days, so the catalogue comes
   round in a few weeks at no extra rate-limit risk.
6. **Documents**: trust boundaries, which secret protects which endpoint, why
   internal HTTP is acceptable, the two-realm login with a sequence diagram,
   and the known gaps.

Deployment order for the MongoDB accounts: push, rebuild the controller image
(the registry is baked in), generate the three secrets, then reconcile the
stack. Until the secrets exist the services stay on the previous credentials.

Done on 2026-09-17: the three secrets exist and every service runs on its own
account. The first attempt failed because the account creator was a separate
image that could not start, and every service waiting for it stayed down
(gateway 502). The accounts are now created from the application image itself.

---

## 11. Phase 9: tests and documentation (done 2026-09-18)

What was built:

1. **Integration tests** (`tests/integration/`, 18 tests) against a real
   MongoDB, seeded with two overlapping catalogues: barcode linking, every
   store combination, browse ordering, group history, the switches, the
   category mapping and its filters, and the cross-store comparison. They seed
   their own database and skip when no MongoDB answers, so a laptop run is
   still ten seconds. A CI job starts MongoDB and runs them; images build only
   after it passes.
2. **Angular specs** for the store selector and the comparison chart, the two
   least covered pieces (19 → 31 tests).
3. **Coverage** from both suites, published as a CI artifact.
4. **Category mapping** (see below), the last feature item.
5. **Documentation**: `README.md`, `docs/architecture.md`, `docs/stores.md`,
   `docs/deployment.md` and eight decision records in `docs/adr/`.
6. **Clean-up**: `respond.json` removed, the empty `templates/` directory
   removed, and `scripts/api_smoke.py` and `scripts/search_eval.py` are now
   tracked — a blanket `scripts/` ignore rule had kept the two scripts the
   documentation tells people to run out of the repository.

Two things found on the way, both pre-existing: the suite's log assertions
depended on whichever test had configured logging first (`pytest.ini` now pins
the level), and six unused imports that `ruff` reports are still there,
untouched, because CI does not run it.

The category mapping replaced item 6 below: Tesco's two top levels are the
canonical vocabulary and Auchan's paths are mapped onto them from the products
both stores sell, one vote per barcode-linked pair, with unmapped paths left
unmapped rather than guessed. See
[adr/0008-learned-category-mapping.md](adr/0008-learned-category-mapping.md).

Not built: the Playwright smoke test (item 3 of the original plan, always
optional), and the alert create → trigger → digest integration path, which
needs the alert service's own async stack and is still covered by its unit
tests.

---

## 12. Phase 10: recommendations across stores (2026-09-18)

The one place the store-neutral design did not hold. Personal picks were
generated from the Tesco catalogue alone: candidates came from the Tesco
collection, the whole path was skipped while Tesco was disabled, and the
categories used for bucketing were Tesco's own strings from the vector payload.
Another store's prices were attached to a pick afterwards by barcode, so a
visitor saw both stores but could never be recommended a product only the other
store sells.

Now, in `stores/recommendations.py`:

1. The alerted products are resolved to offers in **every selected store** -
   a barcode group resolves in each store, a store listing in its own.
2. They are bucketed by the **shared category vocabulary**, not by one store's
   category strings, which is what the Phase 9 mapping made possible.
3. Each bucket's mean vector searches **every selected store's** vectors, and
   hits are filtered back to the bucket's category through the same mapping.
4. A product several stores sell is **one pick** carrying each store's price:
   a recommendation is about a product, not about a listing.
5. Scoring is unchanged, `0.5 x similarity + 0.5 x discount`, so a pick has to
   be both relevant and worth buying.

The Tesco-only gate is gone, so picks work with any store selection, including
one that excludes Tesco. Without vectors, or with none of the watched products
embedded, the answer falls back to the discount rows as before.

The legacy `/api/v1/recommendations/*` endpoints still use the original
Tesco-only engine; they are Tesco-only by definition and return 404 when Tesco
is disabled.

---

### The original phase 9 plan

Tests (each phase also adds its own):

1. CI integration job: `docker compose` with `mongo`, `qdrant`, `api`,
   `alert-service`, a stub `embedding-service`, seeded fixtures for **two
   stores**; search/browse/compare for every store combination, store
   switches, alert create → trigger → digest (email stubbed), recommendations.
2. Angular specs for services, store selector, compare table, alerts (only
   `alerts.spec.ts` exists today).
3. Optional Playwright smoke test: search → group page → compare → alert.
4. Coverage reports as CI artifacts.

Documentation:

1. Root `README.md`: what the system does, services, local run, deployment.
2. `docs/architecture.md`: component diagram including the ecosystem
   (Cloudflare Tunnel → YARP gateway → services, Keycloak, Vector → ClickHouse
   → Grafana, SecretManager, Portainer), store registry and switches, daily
   scrape → link → vectorise → alert flow, search pipeline, auth sequence.
3. `docs/stores.md`: adding a store (adapter, crawler, registry entry,
   scheduler, alert rules, tests) with Auchan as the worked example; how to
   switch stores on and off.
4. `docs/deployment.md`: CI, GHCR images, Portainer, SecretManager, rollback.
5. Decision records (`docs/adr/`): per-store collections + group layer,
   barcode linking, store switches, anonymous Auchan card prices, E5 + Qdrant,
   RRF hybrid search.
6. Category mapping across stores (Tesco and Auchan trees differ), to bring
   back category filters in the store-neutral catalogue.
7. Clean-up: `respond.json`, `versions/*.zip`, `.envbeforethe update`,
   `.env.prodversion`, empty `templates/`.

---

## 13. Milestones

| Milestone | Phases | Result |
|---|---|---|
| M0–M2 | 0–2 | ✅ Store layer and daily Auchan collection live (2026-09-17) |
| M3 | 3 | ✅ Linked products, merged rows, compare and cross-store stats in the API (implemented) |
| M4 | 4 | ✅ Users choose stores and compare prices on the site |
| M5 | 5 | ✅ Store-aware alerts and recommendations |
| M6 | 6 | ✅ Hybrid semantic search across stores, no laptop dependency (implemented) |
| M7 | 7 | ✅ Neutral name and routes live; old routes still work |
| M8 | 8–9 | ✅ Hardened, tested, documented; ready for the thesis |

Deploy note: Portainer pulls images from GHCR. When an image changes, a
controller reconcile alone does not pull it; redeploy the stack.
