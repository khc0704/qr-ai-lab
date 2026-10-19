#!/usr/bin/env bash
# Step 0 of 3 — host preparation (run once, as root / with sudo), before the docker / backend / frontend steps:
#   * service user `qrlab` with a lingering systemd user manager (job cgroup scopes live there)
#   * folders: DATA_ROOT (/srv/qr-ai-lab/data, artifacts / logs / model zoo) and the weight transfer folder
#   * the two environment files from the templates in infra/systemd/ (edit them, then run the next steps)
#   * the checkout is handed to the qrlab user (venvs, node_modules and .next are written there)
# Usage, from the repo checkout (e.g. /opt/qr-ai-lab):   sudo ./infra/install-00-base.sh
set -euo pipefail
if [ "$(id -u)" != 0 ]; then exec sudo -E "$0" "$@"; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${APP_USER:-qrlab}"
DATA_ROOT="${DATA_ROOT:-/srv/qr-ai-lab/data}"
ENV_FILE="/etc/qr-ai-lab/qrlab.env"
FRONT_ENV="/etc/qr-ai-lab/frontend.env"

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$APP_USER"
loginctl enable-linger "$APP_USER"        # user@<uid>.service survives logout / boot; jobs run as transient scopes in it
mkdir -p "$DATA_ROOT/model_zoo" /srv/qr-ai-lab/transfer /etc/qr-ai-lab
chown -R "$APP_USER:$APP_USER" /srv/qr-ai-lab
chown -R "$APP_USER:$APP_USER" "$ROOT"
created=0
for pair in "$ENV_FILE:$ROOT/infra/systemd/qrlab.env.example" "$FRONT_ENV:$ROOT/infra/systemd/frontend.env.example"; do
  dst="${pair%%:*}"; src="${pair#*:}"
  if [ ! -f "$dst" ]; then cp "$src" "$dst"; chmod 640 "$dst"; chown root:"$APP_USER" "$dst"; created=1; echo "created $dst"; fi
done
cat <<MSG
>> base ready: user $APP_USER (uid $(id -u "$APP_USER")), $DATA_ROOT, /srv/qr-ai-lab/transfer, $ROOT owned by $APP_USER
   Next: edit $ENV_FILE and $FRONT_ENV (every comment on its own line — systemd keeps a trailing "# …" as the value),
   then run  ./infra/install-01-docker.sh  →  ./infra/install-02-backend.sh  →  ./infra/install-03-frontend.sh
MSG
[ "$created" = 1 ] && echo "   (the env files were just created from the templates: edit them before step 02 / 03)"
exit 0
