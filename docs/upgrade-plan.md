# Price tracker: upgrade plan (multi-store, store-neutral)

Status: **Phases 0–2 done and deployed (2026-09-17). Phase 3 implemented
(2026-09-17, not yet deployed).** The store-aware frontend comes before alerts
so users see Auchan sooner. Background: [store-spike.md](store-spike.md).

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
| 3 | Barcode linking, merged product rows, compare, cross-store stats, loyalty-price check | ✅ Implemented |
| 4 | Store-aware frontend (selector, badges, compare table); users see Auchan | Next |
| 5 | Store-aware alerts and recommendations | |
| 6 | Semantic and hybrid search across stores | |
| 7 | Neutral name, hostname and routes; ecosystem renames | |
| 8 | Security hardening | |
| 9 | Tests (cross-cutting) and documentation | |

**Auchan card prices (open, decision D3):** anonymous responses contain the
card unit price only for products flagged with a card offer (~380), and those
prices match GVH Árfigyelő. Árfigyelő also shows card prices (mostly a flat
30 % off) for products with no anonymous card data, most likely the ~1,250
card offers listed in category 14288, which is empty for anonymous visitors.
The logged-in reader is not built; see §2.2 D3.

---

## 2. Decisions

### 2.1 Made

| Topic | Decision |
|---|---|
| Second store | **Auchan** (auchan.hu online shop). Penny, Lidl, SPAR, Kifli.hu rejected; see store-spike.md §7 |
| Neutrality | No store is special. Tesco and Auchan are both registry entries and can each be disabled for users |
| Naming | **New neutral site name, hostname and API route.** `/api/tesco/*` and the current hostnames stay as working aliases |
| Default view | **One product row with a price per enabled store.** Barcode-linked products appear once; unlinked and own-brand products appear as single-store rows |
| Alerts | **The user picks stores per alert** (default: all enabled). Fires when any selected store meets the condition. Alerts on disabled stores are paused, not deleted |
| Order | Stores first, then search. Semantic search is built store-aware from the start. Frontend before alerts (revised 2026-09-17) |
| Storage | Separate collections per store; shared layers only join when a query needs it. The Tesco collection is not migrated |
| Loyalty prices | A `loyalty` price channel for every store. Tesco: Clubcard price. Auchan: card price derived from the anonymous card unit price (flagged offers only; see D3) |
| Store switches | Changed with `python -m stores.admin` in the `api` container; no HTTP endpoint, because the gateway forwards every `/api/v1/*` path |
| Git | Commit directly on each repository's default branch; the owner's push releases |

### 2.2 Open

| # | Question | Needed before |
|---|---|---|
| D1 | Neutral site name, public hostname, API route prefix (proposal: `/api/prices/*`) | Phase 7 (UI text can stay neutral earlier) |
| D2 | Host CPU architecture for the embedding model image (compose defaults to `linux/amd64`; the recommendation blueprint and the ARM64 Qdrant build describe a Raspberry Pi 5) | Phase 6 |
| D3 | Auchan card prices beyond the flagged offers: (a) accept partial coverage and label it, (b) take card prices for basic products from GVH Árfigyelő daily, or (c) build the logged-in reader (account terms to check first; prices may depend on the account's loyalty level) | Before comparing "best price" publicly |

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
| Qdrant point ID | hash of the offer reference; existing Tesco points keep `hash(tpnc)` until re-vectorised | – |

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

## 6. Phase 4: store-aware frontend

Goal: users see and choose stores. Branding stays for now (Phase 7), but new
text is written store-neutrally.

1. `StoresService` from `GET /api/v1/stores`; global store chips, remembered
   per visitor (localStorage), overridable per search; hidden when only one
   store is enabled.
2. Search and product list switch to `/search` and `/browse` with `stores`,
   rendering merged group rows: product image and name once, a price per
   store, the cheapest highlighted, store badges on single-store rows.
3. Product page for a group: compare table (regular, promo, card price, unit
   price, availability, link to the store's own page) and one history chart
   with a line per store. Old `/products/{tpnc}` URLs keep working and
   redirect to the group page when the Tesco product is linked.
4. Statistics page: store selector, the per-store charts from `/insights`
   and the comparison from `/insights/compare`; retire `/stats/*` afterwards.
5. Translations (`hu.json`, `en.json`) for store names and new labels.
6. Tests: selector behaviour, hidden selector with one store, group row
   rendering, compare table, legacy URL redirect.

---

## 7. Phase 5: store-aware alerts and recommendations

1. Alert model: `target` = `{kind: "offer", ref}` or `{kind: "group", group_id}`,
   plus `stores: [...]` (default: all enabled at creation).
2. Migration of existing alerts (idempotent script, dry run first):
   `productId` → `target {kind: "offer", ref: "tesco:{productId}"}`,
   `stores: ["tesco"]`. Keep `productId` until the old API is retired.
3. Each store's scheduler triggers the alert service after its run with
   `ref`, `store`, `gtin_norm`; the Auchan scheduler gains the publication step
   the Tesco scraper already has (`runKey` = `{store}:{date}`).
4. Evaluator matches offer alerts by `ref` and group alerts by group
   membership, only for selected and enabled stores. Digest email names the
   store and links to the group page.
5. Frontend: store checkboxes when creating an alert; "paused" badge when every
   selected store is disabled.
6. Recommendations: candidates limited to requested/enabled stores,
   de-duplicated by group; cold-start "best deals" merged across stores.
7. Qdrant payload gains `store`, `ref`, `gtin_norm`; Auchan products are
   vectorised (description and ingredients are already stored).
8. Tests: migration dry run and idempotency, evaluator with store subsets and
   disabled stores, digest grouping, recommendation de-duplication.

---

## 8. Phase 6: semantic and hybrid search

1. `embedding-service` container: FastAPI + CPU `sentence-transformers`,
   `intfloat/multilingual-e5-small` baked into the image, `POST /embed
   {texts, mode: query|passage}` (service adds E5 prefixes), internal network
   and token only, same logging format. Image platform from D2.
2. In-cluster vectorisation after each store run replaces the laptop worker
   for normal operation; `worker.py` stays as a bulk backfill tool.
3. `/search?mode=text|semantic|hybrid` (default `hybrid`): Mongo text results
   and Qdrant results (filtered by stores) fused with Reciprocal Rank Fusion,
   then merged by group. Text results are returned if the vector path fails.
4. `/offers/{ref}/similar` and group-level similar products.
5. Optional: embedding + brand + pack-size matching for products without a
   shared barcode, measured against barcode groups as ground truth.
6. Search evaluation: ~30 labelled Hungarian queries; precision@10 and MRR for
   text / semantic / hybrid; results table in `docs/`.
7. Tests: prefixing, fusion, fallback, store filter in Qdrant queries.

---

## 9. Phase 7: neutral name, routes and ecosystem

1. Apply D1: site name, titles, SEO metadata, footer, privacy policy,
   manifest, translations; no store named in site-wide text.
2. Store-neutral product URLs (`/p/{group_id}`, `/o/{ref}`) with redirects.

| Area | Repo | Change |
|---|---|---|
| Gateway routes | `Gavaller_websites_backend_ecosystem` | New `/api/{prefix}/*` → `api` `/api/v1/*`; keep `/api/tesco/*`; new hostname on the frontend route; keep old hostnames |
| Hostname / tunnel | `DockerNetworkArchitecture` / Cloudflare | New public hostname |
| Keycloak redirect URIs, CORS, auth-gateway return hosts | this repo, SecretManager | Add the new hostname |
| SecretManager | `SecretManager` | Variables in both blocks when new ones appear; redeploy after image tag changes |
| Grafana | `Observability` | Store-neutral folder and titles; store variable on product dashboards |
| RefDataSync + ClickHouse dictionary | `Gavaller_websites_backend_ecosystem`, `ClickHouseInfra` | Product dimension keyed by `ref` with a `store` column; Tesco rows keep `tpnc` |
| Browser extension | this repo | Stays a Tesco-site integration on legacy routes; opens the neutral site |
| TescoDotnetPort | `TescoDotnetPort` | No change (uses `/api/tesco/`) |

---

## 10. Phase 8: security hardening

1. Least-privilege MongoDB users per service; no root credentials in
   application containers.
2. CORS allowlists instead of `*` (`ALLOWED_ORIGINS`, `ALERTS_ALLOWED_ORIGINS`),
   including the new hostname.
3. Trust-boundary document: networks per service, which token protects which
   endpoint, why internal HTTP is acceptable or where TLS is added.
4. Auth realms: document the two-realm flow with a sequence diagram, or
   consolidate.
5. `mongo-express`: admin ingress only, strong basic-auth, or disabled in
   production.
6. Tesco scrape reliability against recurring `429` responses (pacing, thread
   count); several complete days before the thesis presentation.
7. Tesco metadata refresh (fills `deposit_amount` and other fields added after
   a product's first fetch), paced so it does not add rate-limit pressure.

---

## 11. Phase 9: tests and documentation

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
6. Clean-up: `respond.json`, `versions/*.zip`, `.envbeforethe update`,
   `.env.prodversion`, empty `templates/`.

---

## 12. Milestones

| Milestone | Phases | Result |
|---|---|---|
| M0–M2 | 0–2 | ✅ Store layer and daily Auchan collection live (2026-09-17) |
| M3 | 3 | ✅ Linked products, merged rows, compare and cross-store stats in the API (implemented) |
| M4 | 4 | Users choose stores and compare prices on the site |
| M5 | 5 | Store-aware alerts and recommendations |
| M6 | 6 | Hybrid semantic search across stores, no laptop dependency |
| M7 | 7 | Neutral name and routes live; old routes still work |
| M8 | 8–9 | Hardened, tested, documented; ready for the thesis |

Deploy note: Portainer pulls images from GHCR. When an image changes, a
controller reconcile alone does not pull it; redeploy the stack.
