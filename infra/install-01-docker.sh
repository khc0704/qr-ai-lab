#!/usr/bin/env bash
# Step 1 of 3 — MariaDB and Redis in docker compose (the only containers; the app itself runs on the host).
#   * infra/.env holds the registry mirror prefix, DB name / user / passwords and the HOST ports
#     (MARIADB_PORT=3307, REDIS_PORT=6380 by default: 3306 / 6379 are taken on this host)
#   * images come from DOCKER_REGISTRY (company mirror); pull them first if the host has no registry access
# Usage, from the repo checkout:   ./infra/install-01-docker.sh          (needs docker compose v2; no sudo if you are in the docker group)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$ROOT/infra/.env"
command -v docker >/dev/null || { echo "missing: docker (Docker Engine + compose plugin)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "missing: docker compose v2 plugin"; exit 1; }
if [ ! -f "$ENV" ]; then
  cp "$ROOT/infra/.env.example" "$ENV"
  echo ">> created $ENV from the template — set MARIADB_ROOT_PASSWORD / MARIADB_PASSWORD (and DOCKER_REGISTRY), then run again"
  exit 0
fi
grep -qE '^MARIADB_PASSWORD=change-me' "$ENV" && { echo "edit the passwords in $ENV first"; exit 1; }
docker compose -f "$ROOT/infra/docker-compose.yml" --env-file "$ENV" up -d
echo ">> waiting for MariaDB"
for i in $(seq 1 60); do
  docker compose -f "$ROOT/infra/docker-compose.yml" --env-file "$ENV" ps --format '{{.Name}} {{.Health}}' | grep -q "mariadb healthy" && break
  sleep 2
done
docker compose -f "$ROOT/infra/docker-compose.yml" --env-file "$ENV" ps
# shellcheck disable=SC1090
set -a; . "$ENV"; set +a
cat <<MSG
>> MariaDB on 127.0.0.1:${MARIADB_PORT:-3307}, Redis on 127.0.0.1:${REDIS_PORT:-6380}.
   Put the matching values in /etc/qr-ai-lab/qrlab.env:
     DATABASE_URL=mariadb+asyncmy://${MARIADB_USER:-qr}:<MARIADB_PASSWORD>@127.0.0.1:${MARIADB_PORT:-3307}/${MARIADB_DATABASE:-qr_ai_lab}
     REDIS_URL=redis://127.0.0.1:${REDIS_PORT:-6380}/0
MSG
