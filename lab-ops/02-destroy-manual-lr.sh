#!/usr/bin/env bash
# Lab ops — stop/remove a manually created Lightning-Rod (+ volumes).
# Optionally delete the IoTronic board too.
#
# Usage:
#   ./02-destroy-manual-lr.sh lightning-rod-board-lab-...
#   ./02-destroy-manual-lr.sh lightning-rod-board-lab-... --delete-board
#   ./02-destroy-manual-lr.sh          # uses .last-manual-lr.env
#
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "$DIR/env.sh"

DELETE_BOARD=0
NAME=""
for arg in "$@"; do
  case "$arg" in
    --delete-board) DELETE_BOARD=1 ;;
    -*) echo "Unknown flag: $arg"; exit 1 ;;
    *) NAME="$arg" ;;
  esac
done

BOARD_NAME="${BOARD_NAME:-}"
if [[ -z "$NAME" && -f "$DIR/.last-manual-lr.env" ]]; then
  # shellcheck disable=SC1091
  source "$DIR/.last-manual-lr.env"
  NAME="${CONTAINER_NAME:-}"
elif [[ -z "$NAME" && -f /tmp/lab-ops-last-manual-lr.env ]]; then
  # shellcheck disable=SC1091
  source /tmp/lab-ops-last-manual-lr.env
  NAME="${CONTAINER_NAME:-}"
fi

if [[ -z "$NAME" ]]; then
  echo "Usage: $0 <container-name> [--delete-board]"
  exit 1
fi

# Try label for board name
if [[ -z "$BOARD_NAME" ]]; then
  BOARD_NAME="$(docker inspect -f '{{index .Config.Labels "s4t.lab.board_name"}}' "$NAME" 2>/dev/null || true)"
fi
if [[ -z "$BOARD_NAME" ]]; then
  BOARD_NAME="$(docker exec "$NAME" python3 -c "
import json
print(json.load(open('/etc/iotronic/settings.json')).get('iotronic',{}).get('board',{}).get('name',''))
" 2>/dev/null || true)"
fi

echo "=== Destroy $NAME (board=${BOARD_NAME:-unknown}) ==="

# Prefer LR proxy deprovision when available (safe for dynamic only)
if [[ -n "$BOARD_NAME" ]]; then
  curl -sS -X POST "http://127.0.0.1:8092/deprovision" \
    -H 'Content-Type: application/json' \
    -d "{\"board_name\":\"$BOARD_NAME\",\"container\":\"$NAME\"}" \
    | python3 -m json.tool 2>/dev/null || true
fi

if docker inspect "$NAME" >/dev/null 2>&1; then
  echo "-> docker rm -f $NAME"
  docker rm -f "$NAME" >/dev/null
fi

echo "-> removing volumes ${NAME}_*"
for s in var le nginx confs data; do
  docker volume rm -f "${NAME}_${s}" >/dev/null 2>&1 || true
done

if [[ "$DELETE_BOARD" == "1" ]]; then
  if [[ -z "$BOARD_NAME" ]]; then
    echo "WARN: board name unknown; skip IoTronic delete"
  else
    echo "-> deleting IoTronic board '$BOARD_NAME' ..."
    docker exec -i iotronic-ui python2.7 - "$BOARD_NAME" <<'PY'
import json, sys, urllib2, time
name = sys.argv[1]
body = json.dumps({
  "auth": {"identity": {"methods": ["password"], "password": {"user": {
    "name": "admin", "domain": {"name": "Default"}, "password": "s4t"}}},
    "scope": {"project": {"name": "admin", "domain": {"name": "Default"}}}}
})
r = urllib2.urlopen(urllib2.Request(
  "http://keystone:5000/v3/auth/tokens", body,
  {"Content-Type": "application/json"}))
token = r.info().get("X-Subject-Token")
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint="http://iotronic-conductor:8812/v1/")
uid = None
for b in c.board.list():
  if b.name == name:
    uid = b.uuid
    break
if not uid:
  print("board not found")
  raise SystemExit(0)
# wait offline if needed
for _ in range(10):
  b = c.board.get(uid)
  if (getattr(b, "status", "") or "").lower() != "online":
    break
  time.sleep(1)
try:
  c.board.delete(uid)
  print("deleted", name, uid)
except Exception as e:
  print("delete failed:", e)
  raise
PY
  fi
fi

rm -f "$DIR/.last-manual-lr.env" /tmp/lab-ops-last-manual-lr.env
echo "Done."
