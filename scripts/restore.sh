#!/usr/bin/env bash
# Restore a backup made by ./lab backup. The stack must be down; it is started again at the end.
# usage: ./lab restore DIR
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:?usage: ./lab restore DIR}"
P="${COMPOSE_PROJECT_NAME:-s4t}"
[ -f "$DIR/databases.sql" ] || { echo "no databases.sql in $DIR"; exit 1; }
if [ -n "$(docker compose ps -q 2>/dev/null)" ]; then echo "stack is running: ./lab down first"; exit 1; fi
for f in "$DIR"/volumes/*.tgz; do
  v="$(basename "$f" .tgz)"
  short="${v#"${P}"_}"
  docker volume inspect "$v" >/dev/null 2>&1 || docker volume create \
    --label "com.docker.compose.project=$P" --label "com.docker.compose.volume=$short" "$v" >/dev/null
  docker run --rm -v "$v":/v -v "$(cd "$DIR/volumes" && pwd)":/in alpine sh -c "rm -rf /v/* /v/.[!.]* 2>/dev/null; tar xzf /in/$v.tgz -C /v"
  echo "restored $v"
done
./lab up
docker compose stop keystone iotronic-conductor iotronic-wagent iotronic-ui
docker exec -i iotronic-db mysql -uroot -p"${MYSQL_ROOT_PASSWORD:-unime}" < "$DIR/databases.sql"
./lab up
echo "restore complete — run ./lab verify"
