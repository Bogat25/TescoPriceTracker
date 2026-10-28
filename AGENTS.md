<!-- agent-context:kernel:start sha=bc480b1655265682a15a137e9090cd0029723794c5b82eeb54c4cdc7f1eff76f -->
# User repository preferences

- Create commits locally when requested or when completing repository changes.
- Never push commits, create or modify pull requests, trigger GitHub workflows,
  publish releases, or otherwise write to GitHub.
- Treat all GitHub access as read-only unless the user explicitly revokes this
  rule in a later message.
- Commit directly on each repository's default branch (`main`, or `master` where applicable); do not create feature branches.
- Never add `Co-Authored-By` trailers or any AI attribution lines/footers to commits, PRs, files, or documentation.
- Keep commits few per feature (1-2 clean conventional commits); squash or amend unpushed fixups.
- Never read, print, echo, substring, or output plaintext secret values or token fragments anywhere. Test existence only (`Test-Path Env:NAME` or `[bool]$env:NAME`).
- Maintain separate MCP service accounts, tokens, and endpoints for `codex`, `claude`, and `gemini`.
- GitHub exception: all three agents intentionally share one Linux/T3 security boundary. Use your own GitHub App by convention: Codex = `codex` (5516570), Claude = `claude` (5516624), Gemini/Antigravity = `antigravity` (5517659). Never select another agent's App or fall back to a personal GitHub credential. This is an instruction, not enforced isolation between agents.
- For authenticated Git or GitHub CLI commands, use `python3 /home/agent/repos/AgentContext/scripts/setup_github_apps.py run --agent <your-agent> --repo <repository-name> -- git ...` (or `gh ...`). Keep the existing human commit author identity; App credentials identify the pusher and PR author, not the local commit author. Never run credential/token-display commands. If your App is unavailable, report it instead of using another credential. This does not authorize GitHub writes prohibited above.
- Write reports, plans and other documents as Markdown (`.md`) files in the relevant repository or folder. Never publish them as hosted pages (claude.ai Artifacts, Claude Docs or any other agent's equivalent) unless strictly necessary or the user explicitly asks for one.
<!-- agent-context:kernel:end -->

## This repository
<!-- agent-context:contract:start sha=9d0bbd8a08178427e3bad6f880204aab4fd71148886be066ccf891805e72f08e -->
> Synced from `AgentContext/kernel/repos/TescoPriceTracker.md` by `AgentContext/scripts/sync.ps1`. Edit it there, not here.
> `[[name]]` is a platform doc: `AgentContext/corpus/platform/name.md`, or `read("name")` on the agent-context MCP server.

price-tracker.gavaller.com: a store-neutral grocery price tracker (Tesco and Auchan). Python services (scraper, backend-api, alert-service, auth-gateway, scheduler, embedding-service, recommendation system), an Angular frontend and a Chrome extension. The BSc thesis. Default branch **`master`**.

### Test
```sh
python -m pytest -q                                   # unit tests
python -m ruff check .
python -m pytest -q -m integration tests/integration  # two-store integration tests (MongoDB)
cd frontend && npm test -- --watch=false && npm run build
```

### Build
- CI (`.github/workflows/ci.yml`, push to `master` or `v*.*.*` tags) runs the tests, pip-audit, npm audit and a compose config check, then builds the service images to GHCR.

### Deploy
- `tesco-price-tracker` through the controller (Portainer stack id 28): `reconcile_deployments`, then `redeploy_deployment`. Only the redeploy re-pulls images.
- Health checks, rollback and runbooks (scrape did not finish, alerts not delivered, search degraded, stale vectors, missing MongoDB accounts): `docs/deployment.md`.

### Gotchas
- The repository, the Keycloak realm and `/api/tesco` keep the old Tesco-only names; `/api/prices` is the neutral route.
- Product images come from a CDN that blocks headless browsers ([[headless-blocked-by-cdns]]).
- Kifli.hu's robots.txt blocks AI agents: do not access it.

### Docs
`README.md`, `docs/architecture.md`, `docs/stores.md`, `docs/deployment.md`, `docs/adr/`, [[tesco-bsc-thesis-gaps]].
<!-- agent-context:contract:end -->
