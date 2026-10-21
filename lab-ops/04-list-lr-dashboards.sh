#!/usr/bin/env bash
# Lab ops — list every Lightning-Rod dashboard URL (board <-> host port).
# Inside each container LR always serves :1474; the HOST port is what you open.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "$DIR/env.sh"

echo "=== Lightning-Rod dashboards ==="
echo "Host: ${S4T_LAB_HOST}"
echo "Rule: container UI = :1474  |  browser = http://${S4T_LAB_HOST}:<HOST_PORT>/"
echo
printf "%-28s %-32s %-10s %-12s %s\n" "BOARD" "CONTAINER" "HOST_PORT" "STATUS" "URL"
printf "%-28s %-32s %-10s %-12s %s\n" "-----" "---------" "---------" "------" "---"

board_for_static() {
  case "$1" in
    lightning-rod) echo board-alpha ;;
    lightning-rod-2) echo board-beta ;;
    lightning-rod-3) echo board-gamma ;;
    lightning-rod-4) echo board-delta ;;
    lightning-rod-5) echo board-epsilon ;;
    lightning-rod-6) echo board-zeta ;;
    *) echo "" ;;
  esac
}

# Unique LR container names currently running
mapfile -t NAMES < <(docker ps --format '{{.Names}}' | grep -E '^lightning-rod' | sort -u)

for name in "${NAMES[@]}"; do
  ports="$(docker port "$name" 2>/dev/null || true)"
  host_port="$(echo "$ports" | awk -F'[: ]' '/1474\/tcp/{print $NF; exit}')"
  [[ -z "$host_port" ]] && host_port="?"

  board="$(docker inspect -f '{{index .Config.Labels "s4t.lab.board_name"}}' "$name" 2>/dev/null || true)"
  if [[ -z "$board" ]]; then
    board="$(board_for_static "$name")"
  fi
  if [[ -z "$board" ]]; then
    board="$(docker exec "$name" python3 -c "
import json
try:
  b=json.load(open('/etc/iotronic/settings.json')).get('iotronic',{}).get('board',{})
  print(b.get('name') or '')
except Exception:
  print('')
" 2>/dev/null || true)"
  fi
  [[ -z "$board" ]] && board="(unregistered)"

  st="$(docker exec "$name" python3 -c "
import json
try:
  b=json.load(open('/etc/iotronic/settings.json')).get('iotronic',{}).get('board',{})
  print(b.get('status') or 'first_boot')
except Exception:
  print('first_boot')
" 2>/dev/null || echo '?')"

  url="http://${S4T_LAB_HOST}:${host_port}/"
  printf "%-28s %-32s %-10s %-12s %s\n" "$board" "$name" "$host_port" "$st" "$url"
done

echo
echo "Tip: open the URL in the HOST_PORT column for the board you want."
echo "     Host :1474 = board-alpha only. beta=1475 … zeta=1479; manual from 1482+."
echo "Login (after registration): ${LR_UI_USER} / ${LR_UI_PASS}"
