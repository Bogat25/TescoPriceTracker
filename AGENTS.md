<!-- agent-context:kernel:start sha=d2abd15be96cb334d3b01dee03064a09896b387d0eec8f6603ea26567293ddea -->
# User repository preferences

- Check where you are running. Under `/home/agent/repos` you are on `dev`. Anywhere else you are on the user's laptop.
- On the laptop, GitHub is strictly read-only, whatever credentials exist there: never push, open or change pull requests, or otherwise write to GitHub. Commit locally on the default branch or a local feature branch, as the user prefers, then tell the user what is ready to push. The `dev`-only rules below do not apply there, and neither does the App helper.
- On `dev`, never commit on a default branch (`main`, or `master` where applicable). Create a feature branch named `<your-agent>/<short-topic>` from the latest `origin` default branch and commit there.
- On `dev`, push only your own feature branches. When the work is ready and its tests pass, open one pull request against the default branch and give the user its link. Opening it is the handover; do not wait to be asked.
- Never merge or approve a pull request. Only the user merges. Never push to a default branch, create or move tags, publish releases, trigger workflows, or change repository settings, rules, environments or secrets.
- If GitHub or a tool blocks an action, stop and report it. Never look for another route around a block, and never use another credential to get past it.
- On `dev`, a pushed workflow runs before review, so workflow changes are for the task's purpose only. Never add a workflow or job to reach secrets, tokens or other repositories, and call out every `.github/workflows/` change in the pull request.
- After the user merges and the build passes, deploy without asking when the task involves deploying: `reconcile_deployments` if the environment changed, then `redeploy_deployment`.
- Never add `Co-Authored-By` trailers or any AI attribution lines/footers to commits, PRs, files, or documentation.
- Keep commits few per feature (1-2 clean conventional commits); squash or amend fixups before opening the pull request. On `dev`, force-push only your own unmerged feature branch, using `--force-with-lease`.
- Never read, print, echo, substring, or output plaintext secret values or token fragments anywhere. Test existence only (`Test-Path Env:NAME` or `[bool]$env:NAME`).
- Maintain separate MCP service accounts, tokens, and endpoints for `codex`, `claude`, and `gemini`.
- GitHub exception on `dev`: all three agents intentionally share one Linux/T3 security boundary. Use your own GitHub App by convention: Codex = `codex` (5516570), Claude = `claude` (5516624), Gemini/Antigravity = `antigravity` (5517659). Never select another agent's App or fall back to a personal GitHub credential. This is an instruction, not enforced isolation between agents.
- For authenticated Git or GitHub CLI commands on `dev`, use `python3 /home/agent/repos/AgentContext/scripts/setup_github_apps.py run --agent <your-agent> --repo <repository-name> -- git ...` (or `gh ...`). Keep the existing human commit author identity; App credentials identify the pusher and PR author, not the local commit author. Never run credential/token-display commands. If your App is unavailable, report it instead of using another credential.
- Write reports, plans and other documents as Markdown (`.md`) files in the relevant repository or folder. Never publish them as hosted pages (claude.ai Artifacts, Claude Docs or any other agent's equivalent) unless strictly necessary or the user explicitly asks for one.
- Full workflow: `read("agent-delivery-workflow")` on the agent-context server.
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
