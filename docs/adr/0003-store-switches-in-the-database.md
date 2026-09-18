# 3. Store switches live in the database, not in configuration

**Status:** accepted, 2026-09-17

## Context

A store has to be switchable off: a shop may block the scraper, change its API,
or turn out to be legally awkward, and the answer to that cannot be "ship a
release". The alternatives were an environment variable per store (a redeploy
to change), a configuration file in the image (a rebuild and a redeploy), or a
row in the database.

The stack is deployed through Portainer and the SecretManager controller, where
changing an environment value means reconcile plus redeploy - minutes, and a
restart of every service, at a moment when something is already going wrong.

## Decision

The registry lives in the **`stores` collection**, one document per store with
three independent flags:

| Flag | Off means |
|---|---|
| `enabled` | invisible to visitors: no results, no product pages, no alerts, no statistics |
| `scrape_enabled` | no collection; what was already collected stays visible |
| `loyalty_enabled` | the loyalty-price reader does not run |

Changed with `python -m stores.admin set <store> <flag>=<bool>` inside the
`api` container. Every process caches the registry for 60 seconds, and a read
that fails falls back to the compiled-in defaults, so a database hiccup can
never hide every store at once.

There is **no HTTP endpoint**, deliberately: the public gateway forwards every
`/api/v1/*` path, so an endpoint here would be an unauthenticated switch on the
public internet.

## Consequences

- A store can be pulled within a minute, without a deploy, and put back the
  same way.
- Scraping and visibility are separable: a shop that blocks the scraper keeps
  its existing history visible, which is what a shopper wants.
- The switches are operational state, not code, so the repository does not
  record when a store was off. The change is in the logs, not in git.
- Asking for a disabled store by name is a 404 rather than an empty result, so
  a client cannot mistake "switched off" for "no products".
