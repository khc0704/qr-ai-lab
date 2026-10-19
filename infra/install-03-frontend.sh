#!/usr/bin/env bash
# Step 3 of 3 — Next.js frontend.
#   * npm ci (npm reads the company registry from /etc/npmrc; NPM_REGISTRY overrides it for this run)
#   * next build with the public base path from /etc/qr-ai-lab/frontend.env (NEXT_PUBLIC_BASE_PATH, e.g. /ai-lab):
#     the base path is compiled in, so a change there needs a rebuild (= run this script again)
#   * systemd unit qrlab-frontend.service (next start on PORT / HOSTNAME from the env file)
# Requirements: a system-wide node >= 20.9 executable by the qrlab user (e.g. /usr/local/bin/node, not a user's nvm).
# Usage, from the repo checkout:   sudo ./infra/install-03-frontend.sh            # first install
#                                  sudo ./infra/install-03-frontend.sh --update   # after git pull
set -euo pipefail
if [ "$(id -u)" != 0 ]; then exec sudo -E "$0" "$@"; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${APP_USER:-qrlab}"
FRONT_ENV="/etc/qr-ai-lab/frontend.env"
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
UPDATE=0; [ "${1:-}" = "--update" ] && UPDATE=1

[ -n "$NODE_BIN" ] || { echo "missing: node >= 20.9 (install system-wide, e.g. /usr/local/bin/node)"; exit 1; }
[ -f "$FRONT_ENV" ] || { echo "$FRONT_ENV missing: run ./infra/install-00-base.sh first"; exit 1; }
bad="$(grep -nE '^[A-Za-z_][A-Za-z0-9_]*=.*[[:space:]]#' "$FRONT_ENV" || true)"
[ -z "$bad" ] || { echo "$FRONT_ENV must not carry trailing # comments:"; echo "$bad"; exit 1; }
grep -qE '^AUTH_SECRET=change-me' "$FRONT_ENV" && grep -qE '^AUTH_MODE=keycloak' "$FRONT_ENV" && { echo "edit AUTH_SECRET in $FRONT_ENV first"; exit 1; }
chown -R "$APP_USER:$APP_USER" "$ROOT/frontend"
sudo -u "$APP_USER" test -x "$NODE_BIN" || { echo "$NODE_BIN is not executable by $APP_USER (install node system-wide)"; exit 1; }
BASE_PATH="$(grep -E '^NEXT_PUBLIC_BASE_PATH=' "$FRONT_ENV" | cut -d= -f2- || true)"

as_app() {
  local dir="$1"; shift
  sudo -u "$APP_USER" -H env ${NPM_REGISTRY:+npm_config_registry="$NPM_REGISTRY"} NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_BASE_PATH="$BASE_PATH" PATH="$(dirname "$NODE_BIN"):/usr/local/bin:/usr/bin:/bin" \
    bash -c 'cd "$1" && shift && exec "$@"' _ "$dir" "$@"
}
[ "$UPDATE" = 1 ] && { echo ">> stopping frontend"; systemctl stop qrlab-frontend 2>/dev/null || true; }
echo ">> npm ci (registry from /etc/npmrc)"; as_app "$ROOT/frontend" npm ci --no-audit --no-fund
echo ">> next build (NEXT_PUBLIC_BASE_PATH='${BASE_PATH}')"
as_app "$ROOT/frontend" rm -rf .next             # a stale Turbopack cache can keep old prerendered shells
as_app "$ROOT/frontend" npm run build
echo ">> systemd unit"
sed -e "s#/opt/qr-ai-lab#$ROOT#g" -e "s#/usr/local/bin/node#$NODE_BIN#g" \
    "$ROOT/infra/systemd/qrlab-frontend.service" > /etc/systemd/system/qrlab-frontend.service
systemctl daemon-reload
systemctl enable qrlab-frontend >/dev/null
systemctl restart qrlab-frontend
PORT="$(grep -E '^PORT=' "$FRONT_ENV" | cut -d= -f2- || echo 3000)"; PORT="${PORT:-3000}"
for i in $(seq 1 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT${BASE_PATH}/login")" = 200 ] && break; sleep 1; done
systemctl --no-pager --lines=0 status qrlab-frontend || true
echo ">> frontend ready on 127.0.0.1:$PORT${BASE_PATH} — now add the nginx site (infra/nginx/) and reload nginx"
