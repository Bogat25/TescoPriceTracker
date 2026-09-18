# Architecture

How the price tracker is put together: the services, the data, the daily
collection run, and what happens during a request. Written for someone who has
to change or operate it, and for the thesis it belongs to.

Companion documents: [security.md](security.md) (trust boundaries, accounts,
auth), [stores.md](stores.md) (adding a store), [deployment.md](deployment.md)
(pipeline and runbooks), [semantic-search.md](semantic-search.md) (the search
itself), [adr/](adr/) (why the main decisions went the way they did).

---

## 1. What it is

A price tracker for Hungarian grocery shops. It collects every product and
price from each shop once a day, keeps the history, links the same product
across shops by its barcode, and lets a visitor search, compare and be alerted
when a price falls.

It is **store-neutral**: Tesco and Auchan are two stores of equal standing, and
either can be switched off without a redeploy. Tesco came first, which is why
the repository, the Keycloak realm and the legacy `/api/tesco` route still
carry that name.

As of 2026-09-18 it tracks **22,708 Tesco** and **15,201 Auchan** products, of
which **6,228** are linked across both by barcode.

---

## 2. Context

```
     visitor's browser            Chrome extension
            |                            |
            | https                      | https
            v                            v
   +------------------------------------------------+
   |            Cloudflare (DNS, TLS, WAF)           |
   +------------------------------------------------+
            |  Cloudflare Tunnel (no inbound ports)
            v
   +------------------------------------------------+
   |   Gavaller ecosystem: YARP gateway + Keycloak   |
   |   /api/prices/*  ->  price tracker API          |
   |   /api/tesco/*   ->  the same API (alias)       |
   +------------------------------------------------+
            |                         ^
            v                         | logs
   +----------------------+   +-----------------------------+
   |   price tracker      |   |  Vector -> ClickHouse       |
   |   (this repository)  |-->|  -> Grafana dashboards      |
   +----------------------+   +-----------------------------+
            |                         ^
            v                         |
    bevasarlas.tesco.hu         SecretManager controller
    auchan.hu                   (Infisical -> Portainer)
```

The tracker owns nothing outside its own stack. TLS, the public hostname, the
gateway, the identity provider, the log pipeline and the secret delivery all
belong to the surrounding ecosystem; this repository provides one Portainer
stack that plugs into them.

---

## 3. Services

17 containers, 5 networks, 4 volumes. Grouped by what they are for:

| Group | Service | Does |
|---|---|---|
| edge | `frontend` | Angular app served by nginx; also proxies `/api/*` and `/auth/*` to the services below |
| edge | `auth-gateway` | OIDC code flow against Keycloak, keeps the session cookie, hands the frontend a token |
| application | `api` | The catalogue: search, browse, groups, offers, statistics, categories, recommendations |
| application | `alert-service` | Price alerts: create, list, delete, evaluate, send the digest e-mail |
| application | `recommendation-api` | Personal recommendations from the alert history and product vectors, across every selected store |
| collection | `scheduler` | Runs the Tesco scrape once a day and retries an unfinished day |
| collection | `auchan-scheduler` | The same for Auchan |
| search | `embedding-service` | `multilingual-e5-small` behind a small HTTP API |
| search | `vectorizer` | Embeds new and changed products, removes stale points |
| search | `qdrant` | Vector store, one point per offer |
| data | `mongo` | Products, prices, alerts, run states, caches |
| data | `mongo-users` | One-shot: creates the per-service MongoDB accounts, then exits |
| identity | `keycloak` | The `tesco-tracker` realm |
| identity | `keycloak-init`, `keycloak-session-config` | One-shot: data directory ownership, then realm session settings |
| identity | `alert-keycloak-sync` | Keeps the alert service's user cache in step with Keycloak |
| admin | `mongo-express` | Database console on the admin network; off unless explicitly enabled |

Networks: `tesco-tracker-internal` (the stack's own), `public_ingress` and
`admin_ingress` (external, owned by the ecosystem), `gavaller-backend-internal`
(so the gateway can reach the alert service), `tesco-internal`.

---

## 4. Data model

One MongoDB database. Each store keeps **its own collection**, in its own
shape, and the shared code reads through an adapter ([ADR 1](adr/0001-one-collection-per-store.md)).

| Collection | Holds |
|---|---|
| `products` | Tesco products, one document each, with `price_history` per day |
| `auchan_products` | Auchan products, the same idea, Auchan's own fields |
| `stores` | The registry: which stores exist and which switches are on |
| `category_map` | The canonical categories and each store's paths mapped onto them |
| `alerts` | Price alerts and their delivery state |
| `users` | The Keycloak user cache the alert service e-mails from |
| `stats_cache` | Per-store statistics and the cross-store comparison, per day |
| `runs`, `auchan_runs` | One run state per store per day |
| `embedding_state` | What has been vectorised, so the vectorizer can skip it |

### Identifiers

- **`ref`** — one listing in one store: `tesco:121262922`, `auchan:200`.
- **`gtin_norm`** — the barcode without leading zeros. Tesco stores GTIN-14
  with padding, Auchan sends EAN-8 or EAN-13; normalising makes them equal.
- **`group_id`** — `g:{gtin_norm}`, the product across stores. Restricted
  circulation codes (EAN-13 starting with `2`, assigned per shop for weighed
  goods) never get one: equal codes in two shops are not the same product
  ([ADR 2](adr/0002-barcode-as-the-cross-store-key.md)).

### The offer

Every adapter maps its store's document to one shape, so nothing above the
adapter knows a store-specific field name. Tesco's `clubcard` and Auchan's card
price both arrive as `loyalty`:

```
ref, store, store_product_id, gtin, group_id, name, brand, image_url,
category_path, pack_size, pack_unit, is_weighed, availability, url, flags,
prices { regular, promo, loyalty, unit_price, unit }, effective_price,
discount_ratio, price_date
```

A **row** is what the API returns: one product group with every requested
store's offer, cheapest first, plus `best_price`, `cheapest_stores` and
`store_count`. A product only one store sells is a row with one offer.

---

## 5. The daily run

Each store has its own scheduler and its own run state, so one store failing
never holds the other up. A run is resumable: every stage records that it
finished, and a retry repeats only what is unfinished.

```
  scheduler (once a day, retries an unfinished day)
        |
        v
  [1] crawl the shop            page by page, paced; prices saved as they arrive
        |                       a failed page marks the day retryable, not lost
        v
  [2] fetch missing details     descriptions and ingredients for new products
        |
        v
  [3] rebuild statistics        one pass over the store's history -> stats_cache
        |                       and the category mapping, from both catalogues
        v
  [4] price-drop alerts         the alert service is told the day is ready
        |                       not accepted -> retry on the next pass
        v
  [5] vectorise                 only new or changed products are embedded
                                stale points are removed from Qdrant
```

Prices are written in stage 1, so a failure in 3–5 costs a publication, never
data. Stage 4 is the one that can be refused by another service: it sets
`retryable` and logs `scrape.finalization_failed`, and the next pass resends.

---

## 6. A request

**Search** (`GET /api/prices/search?q=tej&stores=&category=`):

```
browser -> Cloudflare -> tunnel -> YARP gateway -> frontend nginx -> api
   |
   api: resolve the stores (registry)  -> resolve the category (category_map)
        |
        +-- text     : Mongo $text per store, narrowed by the store's own paths
        +-- semantic : embedding-service -> Qdrant -> offers from Mongo
        +-- hybrid   : both, fused by Reciprocal Rank Fusion per store
        |
        merge the stores by rank, group by barcode, fill in offers of a linked
        product the other store's result window missed, order offers by price
```

The stores are merged **by rank**, so no store is favoured; within a row the
offers are ordered by price, so the cheapest is first. When the embedding
service or Qdrant is unavailable, search answers from the text index and says
so in the response's `mode` — a degraded answer, never an error.

**Recommendations** start from what the visitor already watches: their alerted
products are bucketed into the shared categories, each bucket's mean vector
finds similar products in every selected store, and candidates are scored
`0.5 x similarity + 0.5 x discount`. A product several stores sell is one pick
carrying each store's price. Anything left over, and everything for a visitor
with no alerts, is filled with the biggest current discounts.

**Alert creation** goes to the alert service instead: the frontend sends the
token it got from the auth gateway, the alert service verifies it against
Keycloak, and stores the alert with the stores the visitor chose.

---

## 7. Observability

Every service logs one JSON line per event with a `Action`, `Category` and the
correlation ID of the request or run — 55 distinct actions. Vector ships them
to ClickHouse, and Grafana reads from there: per-service error rates, scrape
completion, alert delivery, search health. "Healthy" is a finished run per
store per day, no `scrape.finalization_failed`, and no errors from `api`,
`alert-service` or `recommendation-api`.

The alert rules and dashboards live in the Observability repository, not here.

---

## 8. Deployment

Push to `master` → CI (tests, integration tests, audits, Trivy, four images) →
GHCR → Portainer git stack → SecretManager reconcile. The details, including
the trap that only a *redeploy* re-pulls an image, are in
[deployment.md](deployment.md).
