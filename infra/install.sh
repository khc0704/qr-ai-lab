#!/usr/bin/env bash
# Install / update QR AI Lab on an Ubuntu server WITHOUT internet access but WITH a PyPI / npm mirror.
# Usage (as a sudoer, from the repo checkout, e.g. /opt/qr-ai-lab):
#   PIP_INDEX_URL=https://mirror.example.com/pypi/simple NPM_REGISTRY=https://mirror.example.com/npm \
#   ./infra/install.sh            # first install
#   ./infra/install.sh --update   # after git pull: re-sync venvs, rebuild frontend, migrate, restart services
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${APP_USER:-qrlab}"
DATA_ROOT="${DATA_ROOT:-/srv/qr-ai-lab/data}"
ENV_FILE="/etc/qr-ai-lab/qrlab.env"
UPDATE=0; [ "${1:-}" = "--update" ] && UPDATE=1

# mirrors: uv and npm both honour these
export UV_INDEX_URL="${PIP_INDEX_URL:-${UV_INDEX_URL:-}}"
export UV_NATIVE_TLS=1
[ -n "${NPM_REGISTRY:-}" ] && npm config set registry "$NPM_REGISTRY" >/dev/null

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)"; exit 1; }; }
need python3.12 "apt install python3.12 python3.12-venv"
need uv "pipx install uv (from the mirror) or copy the uv binary"
need node "node >= 20.9 from the apt/npm mirror"
need nvidia-smi "NVIDIA driver (only the driver: CUDA libraries come with the torch wheels)"

if [ "$UPDATE" = 0 ]; then
  id -u "$APP_USER" >/dev/null 2>&1 || sudo useradd --system --create-home --shell /bin/bash "$APP_USER"
  sudo loginctl enable-linger "$APP_USER"          # systemd --user manager for the job scopes
  sudo mkdir -p "$DATA_ROOT/model_zoo" /srv/qr-ai-lab/transfer /etc/qr-ai-lab
  sudo chown -R "$APP_USER:$APP_USER" /srv/qr-ai-lab
  [ -f "$ENV_FILE" ] || { sudo cp "$ROOT/infra/systemd/qrlab.env.example" "$ENV_FILE"; sudo chmod 640 "$ENV_FILE"; sudo chown root:"$APP_USER" "$ENV_FILE"; echo ">> edit $ENV_FILE (secrets, DB, Keycloak, mirrors) then re-run"; }
  FRONT_ENV="/etc/qr-ai-lab/frontend.env"
  [ -f "$FRONT_ENV" ] || { sudo cp "$ROOT/infra/systemd/frontend.env.example" "$FRONT_ENV"; sudo chmod 640 "$FRONT_ENV"; sudo chown root:"$APP_USER" "$FRONT_ENV"; echo ">> edit $FRONT_ENV (AUTH_MODE, AUTH_KEYCLOAK_*, AUTH_URL) then re-run"; }
fi

echo ">> backend venv"
(cd "$ROOT/backend" && uv sync --frozen --no-dev --extra gpu)
echo ">> trainer venv (torch + CUDA wheels from the mirror; several GB)"
(cd "$ROOT/trainer" && uv sync --frozen --no-dev --extra dl)
echo ">> frontend build"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && rm -rf .next && NEXT_TELEMETRY_DISABLED=1 npm run build)   # clean: a stale Turbopack cache can keep old prerendered shells

echo ">> database migration"
(cd "$ROOT/backend" && set -a && . "$ENV_FILE" && set +a && .venv/bin/alembic upgrade head && [ "$UPDATE" = 1 ] || .venv/bin/python -m app.cli seed)

echo ">> systemd units"
UID_NUM="$(id -u "$APP_USER")"
for u in qrlab-backend qrlab-scheduler qrlab-frontend; do
  sed -e "s#/opt/qr-ai-lab#$ROOT#g" -e "s#/run/user/1001#/run/user/$UID_NUM#" "$ROOT/infra/systemd/$u.service" | sudo tee "/etc/systemd/system/$u.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now qrlab-backend qrlab-scheduler qrlab-frontend
sudo systemctl restart qrlab-backend qrlab-scheduler qrlab-frontend
sleep 3
systemctl --no-pager --lines=0 status qrlab-backend qrlab-scheduler qrlab-frontend | grep -E "qrlab-|Active"
echo ">> runner check (what the kernel will enforce for jobs):"
curl -s http://127.0.0.1:8000/healthz && echo
echo "   log in as admin and open /admin → 任務執行方式"
