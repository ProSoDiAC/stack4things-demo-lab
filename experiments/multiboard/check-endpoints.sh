#!/usr/bin/env bash
# Multi-board lab helper — verify LR instances and print Horizon URLs
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="${S4T_LAB_HOST:-$(cat "${ROOT}/vm-ip.txt" 2>/dev/null || echo "127.0.0.1")}"

echo "=== Multi-board Lightning-Rod endpoints ==="
for port in 1474 1475 1476; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://${HOST}:${port}/" || echo "000")
  echo "  http://${HOST}:${port}/  HTTP ${code}  (login: me / arancino)"
done

echo ""
echo "=== Horizon IoT Boards ==="
echo "  http://${HOST}/horizon/iot/"
echo ""
echo "Create boards: board-alpha, board-beta, board-gamma"
echo "Map each board to LR on ports 1474, 1475, 1476 respectively"

if docker ps --format '{{.Names}}' | grep -q lightning-rod-2; then
  echo "OK lightning-rod-2 container running"
else
  echo "WARN lightning-rod-2 not running — apply lab overlay and: docker compose up -d lightning-rod-2 lightning-rod-3"
fi
