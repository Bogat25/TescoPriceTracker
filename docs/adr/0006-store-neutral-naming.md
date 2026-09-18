# 6. Store-neutral naming, with the old route kept as an alias

**Status:** accepted, 2026-09-17 (decision D1)

## Context

Everything user-facing said "Tesco": the site name, the page titles, the API
route `/api/tesco/*`. With two stores of equal standing this was no longer
merely untidy - it told visitors that one shop was the subject and the other an
addition.

Renaming has a cost. The Chrome extension in the wild calls `/api/tesco/*`; a
Keycloak realm rename invalidates every session and token; the ClickHouse
product dimension is keyed by `tpnc`; and the repository name appears in image
names and in the deployment configuration.

## Decision

- The product is **Price Tracker**. The hostname `price-tracker.gavaller.com`
  was already neutral and stays.
- The API route becomes **`/api/prices/*`**. **`/api/tesco/*` keeps working**,
  routed to the same service, indefinitely - it is the extension's contract.
- The Keycloak realm keeps the name `tesco-tracker`. Renaming a realm
  invalidates every session and token for a cosmetic gain.
- The repository, the image names and the ClickHouse `tpnc` key keep their
  names for now. They are internal.

## Consequences

- Both routes are part of the supported surface, and
  `scripts/api_smoke.py --route /api/tesco` checks the alias on every deploy.
- The gateway classifies store-neutral endpoints under the new route, so the
  logs and dashboards show the neutral name.
- Internal names and external names now disagree, which will confuse someone
  reading the deployment configuration for the first time. That is written down
  here and in [architecture.md](../architecture.md) rather than fixed, because
  fixing it costs sessions, tokens and a dashboard migration.
- The legacy Tesco-only endpoints (`/products`, `/stats`, `/recommendations`)
  still serve Tesco data only, and return 404 while Tesco is disabled.
