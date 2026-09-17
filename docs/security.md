# Security model

Who can reach what, which secret protects which door, and why the parts that
are not encrypted are still safe. Written for the Phase 8 hardening; the
deployment mechanics are in [upgrade-plan.md](upgrade-plan.md).

---

## 1. Trust boundaries

```
                    Internet
                       │  TLS ends at Cloudflare; the origin has no public port
              ┌────────▼─────────┐
              │ Cloudflare Tunnel│   bot rules, WAF, DDoS
              └────────┬─────────┘
                       │ cloudflared → internal Docker network only
              ┌────────▼─────────┐
              │  YARP gateway    │   OIDC session cookie, rate limits, logging
              │  (ecosystem)     │   /api/prices/*, /api/tesco/*, /api/alerts/*, /auth/*
              └───┬────────┬─────┘
   gavaller-backend-internal   │
                  │            │
        ┌─────────▼──┐   ┌─────▼────────┐
        │ frontend   │   │ api          │  ← no published ports; reachable only
        │ (nginx)    │   │ alert-service│    from the gateway and each other
        └────────────┘   └─────┬────────┘
                               │ tesco-tracker-internal (no egress route in)
   ┌───────────┬───────────┬───┴────────┬──────────────┬───────────────┐
   │ mongo     │ qdrant    │ schedulers │ vectorizer   │ embedding-svc │
   └───────────┴───────────┴────────────┴──────────────┴───────────────┘

   admin_ingress (tailnet only, via the infrastructure nginx):
       mongo (direct), qdrant, mongo-express*, recommendation-api,
       tesco-price-tracker-health (the frontend, for deploy health checks)
       * mongo-express only runs with COMPOSE_PROFILES=admin-tools
```

| Boundary | Enforced by | Notes |
|---|---|---|
| Internet → site | Cloudflare Tunnel | The host has no inbound ports open. Cloudflare answers non-browser clients (scripts, bots) with 403, which is why deploy health checks use an internal address. |
| Site → services | YARP gateway | Single entry for `/api/*` and `/auth/*`. It owns the session cookie and forwards a Bearer token downstream. |
| Service → service | Docker networks | `tesco-tracker-internal` has no route from the internet. A container must be on the network to reach MongoDB, Qdrant or the embedding service. |
| Admin access | Tailnet (`admin_ingress`) | Reachable only from the owner's tailnet, never from the internet. |
| Service → MongoDB | Per-service accounts | Since Phase 8 each service authenticates as itself (§3). |

**Why plain HTTP inside is acceptable.** Every internal hop stays on a Docker
bridge network on one host: the packets never leave the machine, and no
container outside the stack is attached. TLS between containers would add
certificate handling and rotation for traffic that an attacker can only see if
they already have code execution on the host — at which point they can read the
keys too. The boundary that matters (the internet) is TLS-terminated at
Cloudflare. If services are ever split across hosts, this assumption breaks and
mTLS becomes necessary.

---

## 2. Secrets: which key opens which door

| Secret | Protects | Held by |
|---|---|---|
| `INTERNAL_TRIGGER_TOKEN` (Infisical `price_tracker.TESCO_CATALOG_TOKEN`) | `POST /internal/trigger` on the alert service, and the internal catalogue endpoint of the API | schedulers, alert service, API, RefDataSync in the observability stack |
| `GATEWAY_INTERNAL_TOKEN` | The gateway's internal endpoints (JWKS proxy) | gateway, API, alert service |
| `API_KEY` | The upstream Tesco API | scraper |
| `QDRANT_API_KEY` | Qdrant | API, vectorizer, recommendation API |
| `VECTOR_SYNC_API_TOKEN` | The legacy laptop vector sync API | recommendation API (kept until the Phase 9 clean-up) |
| `MONGO_API/SCRAPER/ALERTS_PASSWORD` | The per-service MongoDB accounts | one service group each (§3) |
| `MONGO_INITDB_ROOT_PASSWORD` | MongoDB root | MongoDB itself, the account creator, mongo-express |
| `SESSION_SECRET` | The auth gateway's session cookie | auth gateway |
| `KC_ADMIN_CLIENT_SECRET` | Keycloak admin API (user sync) | alert-service Keycloak sync job |
| `ME_CONFIG_BASICAUTH_PASSWORD` | mongo-express basic auth | mongo-express |

All of them live in Infisical and reach the stack as environment variables
through the SecretManager controller. No secret is committed; `.env` exists
only for local runs. The embedding service deliberately has **no** token: it
holds no data and only turns text into vectors, and it is reachable only from
the internal network (see [semantic-search.md](semantic-search.md) §7.4).

---

## 3. MongoDB: one account per service

Before Phase 8 every service connected as the MongoDB root user, so a bug or a
compromise in any one of them could read or drop everything, including the
alert database. Now:

| Account | Rights | Used by |
|---|---|---|
| `svc_api` | `readWrite` on the catalogue database, `read` on the alert database | api, recommendation-api |
| `svc_scraper` | `readWrite` on the catalogue database | scheduler, auchan-scheduler, vectorizer |
| `svc_alerts` | `readWrite` on the alert database, `read` on the catalogue | alert-service, alert-keycloak-sync |
| root | everything | MongoDB itself, the account creator, mongo-express (admin profile only) |

`mongo/init-users.js` runs on every deploy in the one-shot `mongo-users`
container, with the root account, and creates or updates the three accounts
from the Infisical passwords. It is idempotent, so a password rotation is just
a reconcile. An account whose password is not configured is **skipped**, and
the service keeps working with whatever `MONGO_URI` holds while logging
`mongo.root_credentials` — a half-finished rollout is visible in Grafana
instead of failing or silently staying on root.

---

## 4. Browser-facing policy

* **CORS** (`cors_policy.py`): the API and the alert service accept the site's
  own hostnames plus browser-extension origins (`chrome-extension://…`,
  `moz-extension://…` — Firefox generates that UUID per installation, so only
  the scheme can be pinned). Everything else is refused, so a random page
  cannot read a signed-in user's alerts. A wildcard can still be configured,
  but it drops credentials and logs `cors.wildcard_configured`.
* **Authentication**: alerts and personal recommendations require a verified
  Bearer token; the token never comes from query data (§5).
* **The browser extension** talks to the same public routes with the same
  token; it has no privileged path.

---

## 5. The two Keycloak realms

The stack authenticates against **two** realms, which is easy to misread as a
mistake:

| Realm | Issuer | Purpose |
|---|---|---|
| `backend-ecosystem` | `https://auth.gavaller.com/realms/backend-ecosystem` | The ecosystem-wide login used by the deployed site. The gateway owns the session and issues the tokens services verify. |
| `tesco-tracker` | the stack's own Keycloak container | Stand-alone mode: running the stack on its own (local development, or without the ecosystem gateway) still has a working login. |

Sign-in on the deployed site:

```
browser            frontend/nginx        YARP gateway        Keycloak (backend-ecosystem)      api / alert-service
   │  GET /alerts        │                     │                        │                           │
   ├────────────────────►│                     │                        │                           │
   │  GET /auth/login    │                     │                        │                           │
   ├─────────────────────┼────────────────────►│   OIDC redirect        │                           │
   │◄────────────────────┼─────────────────────┼───────────────────────►│  user signs in            │
   │  session cookie     │                     │◄───────────────────────┤  code → tokens            │
   │◄────────────────────┼─────────────────────┤  (cookie is HttpOnly)  │                           │
   │  GET /auth/token    │                     │                        │                           │
   ├─────────────────────┼────────────────────►│  access token          │                           │
   │◄────────────────────┼─────────────────────┤                        │                           │
   │  GET /api/alerts/  Authorization: Bearer … │                        │                           │
   ├─────────────────────┼────────────────────►├────────────────────────┼──────────────────────────►│
   │                     │                     │                        │  verify signature (JWKS   │
   │                     │                     │                        │  through the gateway),    │
   │                     │                     │                        │  issuer and azp           │
```

Services verify: signature against the realm JWKS (fetched through the
gateway's internal proxy, not the public internet), `iss` against the
configured issuer, `azp` against the expected client, and `exp`/`iat`. The user
identity is always the token's `sub`; no endpoint takes a user ID from a query
parameter (the legacy `/recommendations?userId=` is checked against the token
and rejected with 403 on a mismatch).

---

## 6. Upstream data collection

* Only public product pages and public APIs are read: no login, no paywall, no
  personal data.
* The Tesco scraper paces itself (a floor between requests that doubles after
  every 429) and honours `Retry-After` for all workers, so it cannot hammer the
  upstream even when a pass is retried.
* Auchan is crawled anonymously at one request per second.
* Sites that ask automated clients to stay out are not crawled: Kifli.hu's
  robots rules exclude AI agents, and foodora is behind bot protection that is
  not worked around.

---

## 7. Known gaps

| Gap | Risk | Plan |
|---|---|---|
| The legacy `recommendation-api` and its vector-sync token still run | Extra attack surface for a service nothing calls since Phase 6 | Remove in Phase 9 |
| Keycloak realm name still `tesco-tracker` | Cosmetic only; renaming a realm invalidates sessions | Left as is |
| `.env` on the developer machine holds real values | Local exposure | Stale copies deleted 2026-09-17; the live values are in Infisical |
| No mTLS between containers | Only exploitable with host access | Revisit if the stack spans hosts |
| No automated dependency-update pipeline | Vulnerable versions age in | CI already fails on HIGH/CRITICAL findings (Trivy); updates are manual |
