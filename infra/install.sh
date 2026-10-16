#!/usr/bin/env bash
# Install / update QR AI Lab on an Ubuntu server WITHOUT internet access but WITH a PyPI / npm proxy (e.g. Nexus).
#
# Python packages are installed with pip from backend/requirements.txt and trainer/requirements.txt (exported from
# the uv lockfiles by scripts/export_requirements.sh); pip reads the proxy from /etc/pip.conf
# ([global] index-url = https://nexus.example.com/repository/pypi-proxy/simple), npm from /etc/npmrc
# (registry=https://nexus.example.com/repository/npm-proxy/). uv is NOT needed on the server.
# PIP_INDEX_URL / NPM_REGISTRY in the environment override those files for this run only.
#
# Usage (from the repo checkout, e.g. /opt/qr-ai-lab; the script re-runs itself with sudo):
#   ./infra/install.sh            # 1st run: qrlab user, folders, the two env templates → stops so you can edit them
#   ./infra/install.sh            # 2nd run: venvs, frontend build, migration, seed, systemd services
#   ./infra/install.sh --update   # after git pull: stop services, re-sync venvs, rebuild, migrate, start
# Requirements: python3.12 + venv, a system-wide node >= 20.9 (e.g. /usr/local/bin/node, executable by the
# qrlab user — not one user's nvm), curl; nvidia-smi for GPU jobs.
set -euo pipefail
if [ "$(id -u)" != 0 ]; then exec sudo -E "$0" "$@"; fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${APP_USER:-qrlab}"
DATA_ROOT="${DATA_ROOT:-/srv/qr-ai-lab/data}"
ENV_FILE="/etc/qr-ai-lab/qrlab.env"
FRONT_ENV="/etc/qr-ai-lab/frontend.env"
PYTHON="${PYTHON:-python3.12}"
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
UPDATE=0; [ "${1:-}" = "--update" ] && UPDATE=1

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)"; exit 1; }; }
need "$PYTHON" "apt install python3.12 python3.12-venv (from the apt mirror)"
need curl "apt install curl"
[ -n "$NODE_BIN" ] || { echo "missing: node >= 20.9 (install system-wide, e.g. /usr/local/bin/node)"; exit 1; }
command -v nvidia-smi >/dev/null 2>&1 || echo "WARNING: nvidia-smi not found — jobs will run on CPU only"

# ---- first run: user, folders, env templates --------------------------------------------------------------
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$APP_USER"
loginctl enable-linger "$APP_USER"               # systemd --user manager for the job scopes (survives logout / boot)
mkdir -p "$DATA_ROOT/model_zoo" /srv/qr-ai-lab/transfer /etc/qr-ai-lab
chown -R "$APP_USER:$APP_USER" /srv/qr-ai-lab
fresh=0
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/infra/systemd/qrlab.env.example" "$ENV_FILE"; chmod 640 "$ENV_FILE"; chown root:"$APP_USER" "$ENV_FILE"; fresh=1
fi
if [ ! -f "$FRONT_ENV" ]; then
  cp "$ROOT/infra/systemd/frontend.env.example" "$FRONT_ENV"; chmod 640 "$FRONT_ENV"; chown root:"$APP_USER" "$FRONT_ENV"; fresh=1
fi
if [ "$fresh" = 1 ]; then
  cat <<MSG
>> created $ENV_FILE and $FRONT_ENV from the templates.
   Edit them now (DATABASE_URL, AUTH_SECRET, JOB_TOKEN_SECRET, DATASET_SECRET_KEY, Keycloak, AUTH_URL …):
   every explanation is on its own line — systemd keeps a trailing "# comment" as part of the value.
   Then run ./infra/install.sh again.
MSG
  exit 0
fi

# ---- sanity: env files the way systemd will read them ----------------------------------------------------
bad="$(grep -nE '^[A-Za-z_][A-Za-z0-9_]*=.*[[:space:]]#' "$ENV_FILE" "$FRONT_ENV" || true)"
if [ -n "$bad" ]; then
  echo "env files must not carry trailing # comments (systemd keeps them as part of the value):"; echo "$bad"; exit 1
fi
grep -qE '^(AUTH_SECRET|JOB_TOKEN_SECRET)=change-me' "$ENV_FILE" && { echo "edit the secrets in $ENV_FILE first"; exit 1; }

# the checkout belongs to the service user: venvs, node_modules and .next are written there
chown -R "$APP_USER:$APP_USER" "$ROOT"
sudo -u "$APP_USER" test -x "$NODE_BIN" || { echo "$NODE_BIN is not executable by $APP_USER (install node system-wide)"; exit 1; }

as_app() {  # as_app <dir> <command…>  — run as the service user, in <dir>, with the proxy overrides if given
  local dir="$1"; shift
  sudo -u "$APP_USER" -H env \
    ${PIP_INDEX_URL:+PIP_INDEX_URL="$PIP_INDEX_URL"} ${NPM_REGISTRY:+npm_config_registry="$NPM_REGISTRY"} \
    PATH="$(dirname "$NODE_BIN"):/usr/local/bin:/usr/bin:/bin" NEXT_TELEMETRY_DISABLED=1 \
    bash -c 'cd "$1" && shift && exec "$@"' _ "$dir" "$@"
}

if [ "$UPDATE" = 1 ]; then
  echo ">> stopping services (running jobs are systemd scopes and keep running)"
  systemctl stop qrlab-frontend qrlab-scheduler qrlab-backend || true
fi

venv() {  # venv <dir>: python3.12 venv + pip install -r requirements.txt (pip → /etc/pip.conf → the proxy)
  [ -x "$ROOT/$1/.venv/bin/python" ] || as_app "$ROOT/$1" "$PYTHON" -m venv .venv
  as_app "$ROOT/$1" .venv/bin/pip install --quiet --upgrade pip
  as_app "$ROOT/$1" .venv/bin/pip install --quiet -r requirements.txt
}
echo ">> backend venv"
venv backend
echo ">> trainer venv (torch + CUDA wheels through the proxy; several GB on the first run)"
venv trainer
echo ">> frontend build"
as_app "$ROOT/frontend" npm ci --no-audit --no-fund
as_app "$ROOT/frontend" rm -rf .next        # a stale Turbopack cache can keep old prerendered shells
as_app "$ROOT/frontend" npm run build

echo ">> database migration"
as_app "$ROOT/backend" bash -c "set -a; . $ENV_FILE; set +a; exec .venv/bin/alembic upgrade head"
if [ "$UPDATE" = 0 ]; then
  as_app "$ROOT/backend" bash -c "set -a; . $ENV_FILE; set +a; exec .venv/bin/python -m app.cli seed"
fi

echo ">> systemd units"
UID_NUM="$(id -u "$APP_USER")"
for u in qrlab-backend qrlab-scheduler qrlab-frontend; do
  sed -e "s#/opt/qr-ai-lab#$ROOT#g" -e "s#/run/user/1001#/run/user/$UID_NUM#g" -e "s#user@1001.service#user@$UID_NUM.service#g" \
      -e "s#/usr/local/bin/node#$NODE_BIN#g" -e "s#ReadWritePaths=/srv/qr-ai-lab#ReadWritePaths=/srv/qr-ai-lab $DATA_ROOT#" \
      "$ROOT/infra/systemd/$u.service" > "/etc/systemd/system/$u.service"
done
systemctl daemon-reload
units="qrlab-backend qrlab-frontend"
if grep -qE '^SCHEDULER_EMBEDDED=true' "$ENV_FILE"; then
  systemctl disable --now qrlab-scheduler >/dev/null 2>&1 || true   # the API process runs the scheduler loop
else
  units="$units qrlab-scheduler"
fi
systemctl enable $units >/dev/null
systemctl restart $units

echo ">> waiting for the API and the frontend"
for i in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:8000/healthz && break; sleep 1; done
curl -sf http://127.0.0.1:8000/healthz >/dev/null || { echo "backend is not healthy: journalctl -u qrlab-backend -n 50"; exit 1; }
for i in $(seq 1 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/login)" = 200 ] && break; sleep 1; done
systemctl --no-pager --lines=0 status $units || true
echo ">> done. Log in as admin and check /admin → 任務執行方式 (should say systemd when cgroup limits are active)."
