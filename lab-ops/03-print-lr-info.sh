#!/usr/bin/env bash
# Lab ops — print Lightning-Rod container IP / ports / board mapping.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "$DIR/env.sh"

NAME="${1:-${CONTAINER_NAME:-}}"
if [[ -z "$NAME" ]]; then
  echo "Usage: $0 <container-name>"
  echo "Running LR containers:"
  docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E '^lightning-rod' || true
  exit 1
fi

if ! docker inspect "$NAME" >/dev/null 2>&1; then
  echo "ERROR: container '$NAME' not found"
  exit 1
fi

IP="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")"
NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$NAME")"
PORTS="$(docker port "$NAME" 2>/dev/null || true)"
HOST_PORT="$(echo "$PORTS" | awk -F: '/1474\/tcp/{print $NF; exit}')"

echo "=== Container ==="
echo "name      : $NAME"
echo "network   : $NET"
echo "IP (docker): ${IP:-unknown}"
echo "ports     : ${PORTS:-none}"
echo "LR UI     : http://${S4T_LAB_HOST}:${HOST_PORT:-????}/  (login ${LR_UI_USER}/${LR_UI_PASS})"
echo

echo "=== Board (from /etc/iotronic/settings.json) ==="
docker exec "$NAME" python3 - <<'PY' 2>/dev/null || echo "(settings not ready yet — configure LR first)"
import json
try:
    b = json.load(open("/etc/iotronic/settings.json")).get("iotronic", {}).get("board", {})
except Exception as e:
    print("unreadable:", e)
    raise SystemExit(0)
for k in ("name", "uuid", "code", "status"):
    if k in b:
        print(f"{k:8}: {b.get(k)}")
PY

echo
echo "=== Interfaces inside container ==="
docker exec "$NAME" sh -c 'ip -4 -o addr show 2>/dev/null || ifconfig 2>/dev/null' | sed 's/^/  /'
