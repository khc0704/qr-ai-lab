#!/usr/bin/env bash
# Step 2 of 3 — backend API + scheduler + trainer runtime (host processes, no containers).
#   * backend/.venv and trainer/.venv with pip from requirements.txt (pip reads the company PyPI proxy from
#     /etc/pip.conf; PIP_INDEX_URL overrides it for this run); torch comes first from TORCH_INDEX_URL
#     (default https://download.pytorch.org/whl/cu126 for a CUDA 12.x driver — the wheel bundles its CUDA libraries)
#   * alembic upgrade head (+ seed of system settings / local accounts on the first run)
#   * systemd units qrlab-backend.service and qrlab-scheduler.service (scheduler skipped when SCHEDULER_EMBEDDED=true)
# Usage, from the repo checkout:   sudo ./infra/install-02-backend.sh            # first install
#                                  sudo ./infra/install-02-backend.sh --update   # after git pull
set -euo pipefail
if [ "$(id -u)" != 0 ]; then exec sudo -E "$0" "$@"; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${APP_USER:-qrlab}"
DATA_ROOT="${DATA_ROOT:-/srv/qr-ai-lab/data}"
ENV_FILE="/etc/qr-ai-lab/qrlab.env"
PYTHON="${PYTHON:-python3.12}"
# torch wheels for the host driver: CUDA 12.x driver → cu126 (a company proxy of download.pytorch.org works too)
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
UPDATE=0; [ "${1:-}" = "--update" ] && UPDATE=1

command -v "$PYTHON" >/dev/null || { echo "missing: $PYTHON (apt install python3.12 python3.12-venv)"; exit 1; }
command -v curl >/dev/null || { echo "missing: curl"; exit 1; }
command -v nvidia-smi >/dev/null 2>&1 || echo "WARNING: nvidia-smi not found — jobs will run on CPU only"
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE missing: run ./infra/install-00-base.sh first"; exit 1; }
bad="$(grep -nE '^[A-Za-z_][A-Za-z0-9_]*=.*[[:space:]]#' "$ENV_FILE" || true)"
[ -z "$bad" ] || { echo "$ENV_FILE must not carry trailing # comments (systemd keeps them as the value):"; echo "$bad"; exit 1; }
grep -qE '^(AUTH_SECRET|JOB_TOKEN_SECRET)=change-me' "$ENV_FILE" && { echo "edit the secrets in $ENV_FILE first"; exit 1; }
chown -R "$APP_USER:$APP_USER" "$ROOT/backend" "$ROOT/trainer" "$ROOT/libs"

as_app() {  # as_app <dir> <command…>
  local dir="$1"; shift
  sudo -u "$APP_USER" -H env ${PIP_INDEX_URL:+PIP_INDEX_URL="$PIP_INDEX_URL"} PATH="/usr/local/bin:/usr/bin:/bin" \
    bash -c 'cd "$1" && shift && exec "$@"' _ "$dir" "$@"
}
venv() {
  [ -x "$ROOT/$1/.venv/bin/python" ] || as_app "$ROOT/$1" "$PYTHON" -m venv .venv
  as_app "$ROOT/$1" .venv/bin/pip install --quiet --upgrade pip
  as_app "$ROOT/$1" .venv/bin/pip install --quiet -r requirements.txt
}
if [ "$UPDATE" = 1 ]; then
  echo ">> stopping backend + scheduler (running jobs are systemd scopes and keep running)"
  systemctl stop qrlab-scheduler qrlab-backend 2>/dev/null || true
fi
echo ">> backend venv (pip → /etc/pip.conf proxy)"; venv backend
echo ">> trainer venv: torch first from the CUDA index matching the driver (${TORCH_INDEX_URL}), then the rest"
[ -x "$ROOT/trainer/.venv/bin/python" ] || as_app "$ROOT/trainer" "$PYTHON" -m venv .venv
as_app "$ROOT/trainer" .venv/bin/pip install --quiet --upgrade pip
as_app "$ROOT/trainer" .venv/bin/pip install --quiet -r requirements-torch.txt --index-url "$TORCH_INDEX_URL"
as_app "$ROOT/trainer" .venv/bin/pip install --quiet -r requirements.txt
echo ">> database migration"
as_app "$ROOT/backend" bash -c "set -a; . $ENV_FILE; set +a; exec .venv/bin/alembic upgrade head"
if [ "$UPDATE" = 0 ]; then
  as_app "$ROOT/backend" bash -c "set -a; . $ENV_FILE; set +a; exec .venv/bin/python -m app.cli seed"
fi
echo ">> systemd units"
UID_NUM="$(id -u "$APP_USER")"
for u in qrlab-backend qrlab-scheduler; do
  sed -e "s#/opt/qr-ai-lab#$ROOT#g" -e "s#/run/user/1001#/run/user/$UID_NUM#g" -e "s#user@1001.service#user@$UID_NUM.service#g" \
      -e "s#ReadWritePaths=/srv/qr-ai-lab#ReadWritePaths=/srv/qr-ai-lab $DATA_ROOT#" \
      "$ROOT/infra/systemd/$u.service" > "/etc/systemd/system/$u.service"
done
systemctl daemon-reload
units="qrlab-backend"
if grep -qE '^SCHEDULER_EMBEDDED=true' "$ENV_FILE"; then
  systemctl disable --now qrlab-scheduler >/dev/null 2>&1 || true   # the API process runs the scheduler loop
else
  units="$units qrlab-scheduler"
fi
systemctl enable $units >/dev/null
systemctl restart $units
for i in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:8000/healthz && break; sleep 1; done
curl -sf http://127.0.0.1:8000/healthz >/dev/null || { echo "backend is not healthy: journalctl -u qrlab-backend -n 50"; exit 1; }
systemctl --no-pager --lines=0 status $units || true
echo ">> backend ready on 127.0.0.1:8000 (ROOT_PATH in $ENV_FILE is the external prefix nginx strips, e.g. /ai-lab-api)"
