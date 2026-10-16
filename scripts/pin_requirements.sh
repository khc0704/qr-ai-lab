#!/usr/bin/env bash
# Re-pin backend/requirements.txt, backend/requirements-dev.txt, trainer/requirements.txt and
# trainer/requirements-dev.txt from the dependency ranges in each pyproject.toml.
# Run on a developer machine (pip reads /etc/pip.conf or PIP_INDEX_URL for the company PyPI proxy) after changing
# a pyproject.toml; commit the four files. The server and CI only ever `pip install -r` them.
#   scripts/pin_requirements.sh            # both packages
#   scripts/pin_requirements.sh backend    # one package
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3.12}"
pin() {  # pin <dir> <runtime extras> <dev packages…>
  local dir="$1" extras="$2"; shift 2
  local tmp; tmp="$(mktemp -d)"
  "$PYTHON" -m venv "$tmp/venv"
  local pip="$tmp/venv/bin/pip"
  "$pip" install --quiet --upgrade pip
  "$pip" install --quiet -e "$ROOT/libs/preprocess"
  "$pip" install --quiet "$ROOT/$dir$extras"
  # pip freeze lists the editable package with an absolute path; the repo-relative form is what the server needs
  freeze() { "$pip" freeze --exclude-editable | grep -v -E '^(pip|setuptools|wheel)=='; }
  { echo "# Pinned runtime dependencies for $dir (installed with pip, e.g. by infra/install.sh through the company PyPI proxy)."
    echo "# Regenerate with scripts/pin_requirements.sh after changing pyproject.toml; backend/tests/test_infra_contracts.py checks it."
    echo "-e ../libs/preprocess"; freeze; } > "$ROOT/$dir/requirements.txt"
  "$pip" install --quiet "$@"
  { echo "# Pinned runtime + development dependencies for $dir (pytest, ruff …) for developer machines and CI."
    echo "# Regenerate with scripts/pin_requirements.sh after changing pyproject.toml."
    echo "-e ../libs/preprocess"; freeze; } > "$ROOT/$dir/requirements-dev.txt"
  rm -rf "$tmp"
  echo "wrote $dir/requirements.txt ($(grep -c '==' "$ROOT/$dir/requirements.txt") pins) and $dir/requirements-dev.txt"
}
# `pip install <dir>[extras]` installs the package's own dependencies; the packages themselves are not installed
# (they are run from the checkout), so freeze only lists their dependencies.
case "${1:-all}" in
  backend) pin backend "[gpu]" "pytest>=8" "pytest-asyncio>=0.23" "ruff>=0.5" "anyio>=4" ;;
  trainer) pin trainer "[dl]" "pytest>=8" "ruff>=0.5" ;;
  all) pin backend "[gpu]" "pytest>=8" "pytest-asyncio>=0.23" "ruff>=0.5" "anyio>=4"
       pin trainer "[dl]" "pytest>=8" "ruff>=0.5" ;;
  *) echo "usage: $0 [backend|trainer|all]"; exit 1 ;;
esac
