#!/usr/bin/env bash
# Full functional test suite. Needs a bootstrapped stack (./lab up && ./lab bootstrap).
#   tests/run-all.sh          # everything (~3 min)
#   tests/run-all.sh quick    # skip the slow FL training and dynamic-board tests
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
quick=0; [ "${1:-}" = "quick" ] && quick=1
pass=0; failed=()

run() {
  local name="$1"; shift
  printf '\n=== %s ===\n' "$name"
  if "$@"; then pass=$((pass+1)); echo "--> PASS: $name"; else failed+=("$name"); echo "--> FAIL: $name"; fi
}

run "stack health (verify-demo, check only)" python3 scripts/verify-demo.py --check-only
run "Horizon login + every IoT panel"          python3 tests/horizon-smoke.py
run "metrics E2E (gateway, Influx, Grafana)"   python3 experiments/metrics/verify-metrics-lab.py
run "fleets 360 (CRUD, inject, call, logs)"    python3 experiments/multiboard/verify-fleet-360.py
if [ "$quick" = 0 ]; then
  run "federated learning (heart + PM, 3 boards)" bash experiments/federated-learning/test-fl-workflows.sh
  run "dynamic board (provision, online, delete)" python3 tests/dynamic-board.py
fi

echo
echo "=============================="
echo " passed: $pass   failed: ${#failed[@]}"
for f in "${failed[@]:-}"; do [ -n "$f" ] && echo "  x $f"; done
echo "=============================="
[ "${#failed[@]}" -eq 0 ]
