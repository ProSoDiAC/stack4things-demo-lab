#!/usr/bin/env bash
# IoTronic networking API helpers — Module E (virtual networking).
# usage: ./attach-port.sh boards | list [BOARD_UUID] | attach BOARD_UUID NETWORK_UUID
set -euo pipefail

CONDUCTOR="${S4T_CONDUCTOR:-http://127.0.0.1:8812}"
KEYSTONE="${S4T_KEYSTONE:-http://127.0.0.1:5000/v3}"
ADMIN_PASS="${ADMIN_PASS:-s4t}"

token() {
  curl -si "${KEYSTONE}/auth/tokens" -H 'Content-Type: application/json' -d "{\"auth\":{\"identity\":{\"methods\":[\"password\"],\"password\":{\"user\":{\"name\":\"admin\",\"domain\":{\"name\":\"Default\"},\"password\":\"${ADMIN_PASS}\"}}},\"scope\":{\"project\":{\"name\":\"admin\",\"domain\":{\"name\":\"Default\"}}}}}" \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="x-subject-token"{print $2}'
}
TOKEN="$(token)"
[[ -n "$TOKEN" ]] || { echo "cannot get a Keystone token from ${KEYSTONE}" >&2; exit 1; }
api() { curl -s -H "X-Auth-Token: ${TOKEN}" -H 'Content-Type: application/json' "$@"; }
pp() { python3 -m json.tool 2>/dev/null || cat; }

case "${1:-}" in
  boards) api "${CONDUCTOR}/v1/boards/" | pp ;;
  list)
    if [[ -n "${2:-}" ]]; then api "${CONDUCTOR}/v1/boards/${2}/ports/" | pp; else api "${CONDUCTOR}/v1/ports/" | pp; fi ;;
  attach)
    [[ -n "${2:-}" && -n "${3:-}" ]] || { echo "usage: $0 attach BOARD_UUID NETWORK_UUID" >&2; exit 1; }
    api -X POST "${CONDUCTOR}/v1/boards/${2}/ports/" -d "{\"network\": \"${3}\"}" | pp ;;
  *) echo "Commands: boards | list [BOARD_UUID] | attach BOARD_UUID NETWORK_UUID  (conductor: ${CONDUCTOR})" ;;
esac
