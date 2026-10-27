#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, push, and deploy Tesco Price Tracker
# =============================================================================
# Usage:
#   ./deploy.sh [--skip-extension] [--skip-push] [--skip-deploy]
#
# Prerequisites:
#   - Docker logged in to GHCR (docker login ghcr.io -u <user> -p <PAT>)
#   - ssh-agent loaded with the server's private key
#   - .env present at project root (used for GHCR_USERNAME etc.)
#   - Node.js + npm installed (for extension build)
#   - SSH_HOST and SSH_STACK_PATH set either in .env or as env vars below
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Config defaults (override via .env or environment) ──────────────────────
: "${GHCR_USERNAME:=bogat25}"
: "${GHCR_PAT:=}"            # Personal Access Token with packages:write scope
: "${SSH_HOST:=}"            # e.g. user@server.example.com
: "${SSH_STACK_PATH:=}"      # e.g. /opt/portainer/stacks/tesco-tracker

# Load .env if it exists (for local dev)
if [[ -f .env ]]; then
  # Export only non-empty, non-comment lines
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | grep -v '^\s*$')
  set +a
fi

# ── CLI flags ────────────────────────────────────────────────────────────────
SKIP_EXTENSION=false
SKIP_PUSH=false
SKIP_DEPLOY=false
PUBLISH_EXTENSION=false

for arg in "$@"; do
  case "$arg" in
    --skip-extension) SKIP_EXTENSION=true ;;
    --publish-extension) PUBLISH_EXTENSION=true ;;
    --skip-push)      SKIP_PUSH=true ;;
    --skip-deploy)    SKIP_DEPLOY=true ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--skip-extension] [--publish-extension] [--skip-push] [--skip-deploy]"
      exit 1
      ;;
  esac
done

BACKEND_IMAGE="ghcr.io/${GHCR_USERNAME}/tescopricetracker:latest"
FRONTEND_IMAGE="ghcr.io/${GHCR_USERNAME}/tesco-tracker-frontend:latest"

echo "============================================================"
echo "  Tesco Price Tracker — Deploy"
echo "  Backend image : $BACKEND_IMAGE"
echo "  Frontend image: $FRONTEND_IMAGE"
echo "============================================================"

# ── 0. GHCR login ────────────────────────────────────────────────────────────
if [[ -n "$GHCR_PAT" ]]; then
  echo ""
  echo "▶  Logging in to GHCR…"
  echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
  echo "  ✓ Logged in to ghcr.io as ${GHCR_USERNAME}"
else
  echo "  ℹ  GHCR_PAT not set — assuming already logged in to ghcr.io"
fi

# ── 1. Build browser extension ───────────────────────────────────────────────
if [[ "$SKIP_EXTENSION" == "false" ]]; then
  echo ""
  echo "▶  Building browser extension…"
  pushd "$SCRIPT_DIR/extension" > /dev/null
  node build.js
  echo "  ✓ Extension packages built (dist/)"

  if [[ "$PUBLISH_EXTENSION" == "true" ]]; then
    echo ""
    echo "▶  Publishing extension to browser stores…"
    node publish.js
    echo "  ✓ Extension publish complete"
  fi

  popd > /dev/null
else
  echo "  ⏭  Skipping extension build (--skip-extension)"
fi

# ── 2. Build Docker images ───────────────────────────────────────────────────
echo ""
echo "▶  Building backend Docker image…"
docker build \
  --platform linux/amd64 \
  -t "$BACKEND_IMAGE" \
  "$SCRIPT_DIR"
echo "  ✓ Backend image built"

echo ""
echo "▶  Building frontend Docker image…"
docker build \
  --platform linux/amd64 \
  -t "$FRONTEND_IMAGE" \
  "$SCRIPT_DIR/frontend"
echo "  ✓ Frontend image built"

# ── 3. Push images to GHCR ──────────────────────────────────────────────────
if [[ "$SKIP_PUSH" == "false" ]]; then
  echo ""
  echo "▶  Pushing images to GHCR…"
  docker push "$BACKEND_IMAGE"
  docker push "$FRONTEND_IMAGE"
  echo "  ✓ Images pushed"
else
  echo "  ⏭  Skipping image push (--skip-push)"
fi

# ── 4. Deploy on remote server ───────────────────────────────────────────────
if [[ "$SKIP_DEPLOY" == "false" ]]; then
  if [[ -z "$SSH_HOST" || -z "$SSH_STACK_PATH" ]]; then
    echo ""
    echo "  ⚠  SSH_HOST or SSH_STACK_PATH not set — skipping remote deploy."
    echo "     Set them in .env or export before running this script:"
    echo "       SSH_HOST=user@server.example.com"
    echo "       SSH_STACK_PATH=/opt/portainer/stacks/tesco-tracker"
  else
    echo ""
    echo "▶  Deploying on $SSH_HOST at $SSH_STACK_PATH…"
    # shellcheck disable=SC2029
    ssh "$SSH_HOST" "
      set -e
      cd '${SSH_STACK_PATH}'
      echo '  → Pulling new images…'
      docker compose pull --quiet
      echo '  → Recreating updated containers…'
      docker compose up -d --remove-orphans
      echo '  → Pruning dangling images…'
      docker image prune -f --filter 'dangling=true'
      echo '  ✓ Deploy complete'
    "
    echo "  ✓ Remote deploy finished"
  fi
else
  echo "  ⏭  Skipping remote deploy (--skip-deploy)"
fi

echo ""
echo "============================================================"
echo "  ✅  All done!"
echo "============================================================"
