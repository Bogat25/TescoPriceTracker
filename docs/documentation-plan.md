# Documentation plan (Phase 9)

Preparation only: what will be written, what each piece must contain, and where
the facts come from. Nothing here is the documentation itself — it is the
outline to write from, so no time is lost re-deriving facts that are already
established.

Existing documents that stay and are linked from the new ones:

| Document | Covers |
|---|---|
| [semantic-search.md](semantic-search.md) | Search: model, indexing, fusion, operations, measurements |
| [search-eval.md](search-eval.md) | Measured search quality and the threshold calibration |
| [security.md](security.md) | Trust boundaries, secrets, MongoDB accounts, CORS, auth realms |
| [store-spike.md](store-spike.md) | Why Auchan, and why not Penny, Lidl, SPAR, Kifli |
| [upgrade-plan.md](upgrade-plan.md) | The plan, decisions and per-phase results |
| [manual-test-plan.md](manual-test-plan.md) | What a person checks in the browser |

---

## 1. `README.md` (root)

For someone who lands on the repository and has five minutes.

1. What the system does, in three sentences, with one screenshot.
2. What it tracks today: two stores, daily prices, ~22,700 Tesco and ~15,000
   Auchan products, barcode-linked rows, alerts, hybrid search.
3. Quick architecture picture (one diagram, the detail lives in
   `architecture.md`).
4. Run it locally: prerequisites, `.env.example` → `.env`, `docker compose up`,
   the first-run notes (Keycloak realm, empty database, no vectors yet).
5. Run the tests: `pytest`, `npx ng test`, what each covers.
6. Where everything else is documented (the table above).

Sources: `docker-compose.yml`, `.env.example`, `pytest.ini`, this plan.

## 2. `docs/architecture.md`

The main technical document; the one the thesis leans on.

1. **Context**: users, the browser extension, the two shops, the ecosystem
   (Cloudflare Tunnel → YARP gateway → services, Keycloak, Vector → ClickHouse
   → Grafana, SecretManager/Infisical, Portainer).
2. **Services** (17 containers): purpose, image, what it talks to. Group them:
   edge (frontend, auth-gateway), application (api, alert-service,
   recommendation-api), collection (scheduler, auchan-scheduler), search
   (embedding-service, vectorizer, qdrant), data (mongo, mongo-users),
   identity (keycloak + init jobs), admin (mongo-express).
3. **Data model**: `products`, `auchan_products`, `stores`, `alerts`,
   `stats_cache`, `embedding_state`, run states; the `Offer` model and the
   `ref` / `g:{gtin}` identifiers; why one collection per store.
4. **The daily flow**: scrape → save prices → statistics → price-drop alerts →
   vectorize, per store, with the run-state machine and what happens when a
   step fails (the retry and publication rules).
5. **The request flow**: search, product page, alert creation — each as a
   sequence of hops.
6. **Observability**: the log contract (52 distinct `Action` values), Vector,
   ClickHouse, the dashboards and the alert rules; what "healthy" looks like.
7. **Deployment**: CI → GHCR → Portainer git stacks → SecretManager reconcile;
   the health-check rule (internal address, because the edge blocks scripts).

Diagrams needed (ASCII, like the existing docs, so they survive in git):
context, container, daily flow, search request, auth sequence (already in
`security.md`, link rather than repeat).

Sources: `docker-compose.yml`, `stores/`, `scraper/scraper.py`,
`stores/auchan/crawler.py`, `alert-service/`, the Observability repo,
`SecretManager/config/deployments.yaml`.

## 3. `docs/stores.md` — adding a store

A worked recipe, with Auchan as the example, because this is the claim the
"store-neutral" design makes.

1. What a store needs: a listing source, stable product IDs, barcodes, prices.
2. Steps: client → mapper → repository → adapter (`search`, `browse`,
   `find_by_ids`, `find_by_gtins`, `get_offer`, `get_history`,
   `iter_histories`) → registry entry → crawler and scheduler → embedding text
   → alert feed → Grafana rules → tests.
3. The switches (`enabled`, `scrape_enabled`) and what each turns off.
4. What is store-specific and must not leak into shared code.
5. A checklist to copy for the next store.

Sources: `stores/auchan/*`, `stores/registry.py`, `stores/queries.py`,
`stores/embedding_text.py`, `stores/alerts_feed.py`.

## 4. `docs/deployment.md`

1. The pipeline: push → CI (tests, Trivy, four images) → GHCR → Portainer.
2. SecretManager: what `reconcile` does versus `redeploy`, and the trap that
   only `redeploy` re-pulls images.
3. Secrets: where they live, how to add one, how to rotate one.
4. Health checks and the rollback behaviour (a failed health check rolls the
   environment back).
5. Rollback: previous image tag, previous git revision.
6. Runbooks: scrape did not finish, alerts not delivered, vectors stale, search
   degraded, MongoDB accounts missing — each with the log action to look for
   and the fix.

Sources: `.github/workflows/ci.yml`, SecretManager `DEPLOYMENT.md`, the Grafana
alert rules, the incidents already recorded in `upgrade-plan.md`.

## 5. `docs/adr/` — decision records

Short, one page each: context, decision, consequences. Drafted from
`upgrade-plan.md` §2 and the phase sections, so the reasoning is already
written; these only restate it in a form a reader can cite.

1. One collection per store, with a shared offer layer.
2. Barcode (`gtin_norm`) as the cross-store product key, and why restricted
   codes are excluded.
3. Store switches in the database rather than in configuration.
4. Auchan card prices: partial coverage accepted and labelled (D3).
5. `multilingual-e5-small` + Qdrant + Reciprocal Rank Fusion (D2 host, too).
6. Store-neutral naming with the old route kept as an alias (D1).
7. Per-service MongoDB accounts with a visible fallback.

## 6. Category mapping (feature, not documentation)

Needed before the catalogue can offer category filters again and before
cross-store personal recommendations. Approach to evaluate: map Auchan's
category paths to Tesco's using the products already linked by barcode (about
6,200 of them are ground truth), then measure how much of each catalogue the
mapping covers.

---

## Facts already measured (do not re-derive)

| Fact | Value | Source |
|---|---|---|
| Catalogue size | 22,708 Tesco + 15,036 Auchan | `/browse` totals, 2026-09-17 |
| Linked products | 6,221 | Phase 3 deployment check |
| Cheapest-by-regular-price | Tesco 2,981 · Auchan 1,720 · ties 1,520 | Phase 3 |
| Price index vs cheapest | Tesco 102.75 · Auchan 107.73 | Phase 3 |
| Search quality (P@10) | text 0.78 · semantic 0.82 · hybrid 0.87 | `search-eval.md` |
| Embedding throughput | 172 passages/s on 4 CPUs; 7–8 ms per query; 707 MiB | Phase 6 container run |
| Full indexing time | ~4–8 min for 37,700 products | Phase 6 |
| Services | 17 containers, 5 networks, 4 volumes | `docker-compose.yml` |
| Log vocabulary | 52 distinct `Action` values | repository grep |
| Tests | 322 backend · 18 frontend · 75 observability | test runs, 2026-09-17 |
| API endpoints | 51 routes in the API and alert service | repository grep |

## Screenshots to take (for README and the thesis)

Search results with two stores · a comparison page with the history chart ·
the alert form with store chips · the alerts page · the statistics compare tab ·
a Grafana dashboard · the extension on a Tesco page.

## Open questions before writing

1. Audience for the README: contributors, or thesis readers? (Affects how much
   context each document repeats.)
2. Language: English throughout, or Hungarian for the thesis-facing parts?
3. Does the thesis need its own document in this repository, or does it only
   cite these?
