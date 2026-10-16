#!/usr/bin/env bash
# Re-export backend/requirements.txt and trainer/requirements.txt from the uv lockfiles.
# Run on a developer machine after `uv lock` / `uv add …`; the server installs these with pip (through the
# company PyPI proxy in /etc/pip.conf) and never needs uv. backend/tests/test_infra_contracts.py checks they match.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export_one() {
  local dir="$1" extra="$2"
  (cd "$ROOT/$dir" && uv export --frozen --no-dev --no-hashes --extra "$extra" -o requirements.txt >/dev/null)
  # the second comment line of the export carries this machine's output path; keep it stable
  sed -i "2s#.*#\#    scripts/export_requirements.sh (uv export --frozen --no-dev --no-hashes --extra $extra); install with pip from the company PyPI proxy#" "$ROOT/$dir/requirements.txt"
  echo "wrote $dir/requirements.txt ($(grep -c '==' "$ROOT/$dir/requirements.txt") pinned packages)"
}
export_one backend gpu
export_one trainer dl
