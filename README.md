# Price Tracker

Tracks grocery prices in Hungarian webshops. It collects every product and
price once a day, keeps the history, links the same product across shops by its
barcode, and tells you when something you watch gets cheaper.

Live: **https://price-tracker.gavaller.com**

It started as a Tesco-only tracker — which is what the repository, the Keycloak
realm and the legacy `/api/tesco` route are still named after — and is now
store-neutral: every store is equal, and any of them can be switched off
without a redeploy.

---

## What it tracks today

| | |
|---|---|
| Stores | Tesco and Auchan |
| Products | 22,708 Tesco + 15,201 Auchan (2026-09-18) |
| Linked across both | 6,228, by barcode |
| History | One snapshot per product per day, since May 2026 |
| Prices per product | regular, promotional and loyalty-card |

**Features.** Search by words or by meaning (hybrid, Hungarian); a product row
showing each store's price with the cheapest first; filtering by a category
vocabulary learned from the products the stores share; price history charts per
store; price-drop and target-price alerts by e-mail, per store; cross-store
comparison and per-store statistics; personal recommendations drawn from every
store you have selected; a Chrome extension that shows the price history on a
Tesco product page.

---

## How it fits together

```
  browser / extension
        |
  Cloudflare -> tunnel -> YARP gateway -> frontend (nginx + Angular)
                                             |
                    +------------------------+------------------------+
                    |                        |                        |
                   api               alert-service           recommendation-api
                    |                        |                        |
                    +---------- MongoDB -----+        Qdrant + embedding-service
                    |
       scheduler / auchan-scheduler  ->  the shops, once a day
```

17 containers in one Portainer stack. The full picture, the data model and the
daily run are in **[docs/architecture.md](docs/architecture.md)**.

---

## Running it locally

Needs Docker and about 4 GB of RAM (the embedding model is the hungry part).

```bash
git clone https://github.com/Bogat25/TescoPriceTracker.git
cd TescoPriceTracker
cp .env.example .env          # safe defaults; nothing secret is committed
docker compose up -d
```

The site is then on http://localhost, the API on `/api/prices`.

First run, in order of appearance:

- The **database is empty**. Nothing is on the site until a scrape has run; the
  schedulers start one on their own schedule, or you can trigger one:
  ```bash
  docker compose exec scheduler python -c "from scraper import scraper; scraper.run_scrape()"
  docker compose exec auchan-scheduler python -c "from stores.auchan import crawler; crawler.run_crawl()"
  ```
- **Search has no vectors** until the vectorizer has run after a scrape. Until
  then search answers from the text index, which is a supported degraded mode,
  not a failure.
- **Keycloak** creates its realm on first start; logging in works once it is up.
- Switching a store off, and rebuilding the category mapping:
  ```bash
  docker compose exec api python -m stores.admin list
  docker compose exec api python -m stores.admin set auchan enabled=false
  docker compose exec api python -m stores.admin categories
  ```

---

## Tests

```bash
python -m pytest -q                       # 381 unit tests, ~10 s
cd frontend && npm test -- --watch=false  # 43 Angular tests
```

The unit tests fake every service, so they need nothing running. The
integration tests need a MongoDB and skip without one:

```bash
docker run -d -p 27017:27017 mongo:8
python -m pytest -q -m integration tests/integration     # 18 tests
```

They seed their own database (`tesco_tracker_integration`) and never touch the
one the application is configured with. CI runs all three, plus `pip-audit`,
`npm audit` and Trivy, and publishes a coverage report.

After deploying, `python scripts/api_smoke.py` checks 19 public endpoints
against the live site.

---

## Documentation

| Document | Covers |
|---|---|
| [architecture.md](docs/architecture.md) | Services, data model, the daily run, a request end to end |
| [stores.md](docs/stores.md) | Adding a store, with Auchan as the worked example; the switches |
| [deployment.md](docs/deployment.md) | CI, GHCR, Portainer, SecretManager, rollback, runbooks |
| [security.md](docs/security.md) | Trust boundaries, MongoDB accounts, CORS, the two realms |
| [semantic-search.md](docs/semantic-search.md) | The model, indexing, fusion, operations |
| [recommendations.md](docs/recommendations.md) | What gets recommended and why, the scoring, the limits |
| [search-eval.md](docs/search-eval.md) | Measured search quality and the similarity threshold |
| [store-spike.md](docs/store-spike.md) | Why Auchan, and why not Penny, Lidl, SPAR or Kifli |
| [adr/](docs/adr/) | The decisions behind the design, one page each |
| [upgrade-plan.md](docs/upgrade-plan.md) | The multi-store rebuild, phase by phase |
| [manual-test-plan.md](docs/manual-test-plan.md) | What a person checks in a browser |

---

## Licence

MIT, see [LICENSE](LICENSE). An independent project for educational purposes;
not affiliated with Tesco or Auchan.
