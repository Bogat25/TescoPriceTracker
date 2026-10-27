#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runner="${ARKPLUS_LINUX_RUNNER:-$repo_root/../AgentContext/scripts/linux_workspace.py}"
if [[ ! -f "$runner" ]]; then
  printf 'Clone AgentContext beside this repository, or set ARKPLUS_LINUX_RUNNER to its scripts/linux_workspace.py.\n' >&2
  exit 2
fi
exec python3 "$runner" --repo "$repo_root" "$@"
