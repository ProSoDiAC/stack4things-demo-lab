#!/usr/bin/env bash
# Backup everything stateful: MariaDB dump + every named volume of the project (except DB files/logs).
# usage: ./lab backup [DIR]
set -euo pipefail
cd "$(dirname "$0")/.."
P="${COMPOSE_PROJECT_NAME:-s4t}"
DIR="${1:-backups/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$DIR/volumes"
echo "-> database dump"
docker exec iotronic-db mysqldump -uroot -p"${MYSQL_ROOT_PASSWORD:-unime}" --all-databases --single-transaction --routines > "$DIR/databases.sql"
echo "-> volumes"
for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$P"); do
  case "$v" in
    *unime_iotronic_db_data|*_logs|*_apache_logs) continue ;;   # DB is restored from the dump; logs are disposable
  esac
  docker run --rm -v "$v":/v:ro -v "$(cd "$DIR/volumes" && pwd)":/out alpine tar czf "/out/$v.tgz" -C /v .
  echo "   $v"
done
cp .env "$DIR/env.backup" 2>/dev/null || true
echo "backup written to $DIR"
