#!/bin/bash
# Runs once, on the first start of the mariadb container (docker-entrypoint-initdb.d). The database and the
# application user already exist (MARIADB_DATABASE / MARIADB_USER); this fixes the charset and adds the test DB.
set -euo pipefail
db="${MARIADB_DATABASE:-qr_ai_lab}"
user="${MARIADB_USER:-qr}"
mariadb -uroot -p"${MARIADB_ROOT_PASSWORD}" <<SQL
ALTER DATABASE \`${db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS \`${db}_test\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON \`${db}_test\`.* TO '${user}'@'%';
FLUSH PRIVILEGES;
SQL
