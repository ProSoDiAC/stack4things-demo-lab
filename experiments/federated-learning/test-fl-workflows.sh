#!/usr/bin/env bash
# E2E workflow smoke tests for FL Horizon lab (heart + PM).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FL="$ROOT/experiments/federated-learning"
PASS=0
FAIL=0

ok() { echo "  OK  $1"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $1"; FAIL=$((FAIL + 1)); }

wait_state() {
  local tries="${1:-30}"
  local check="$2"
  for _ in $(seq 1 "$tries"); do
    if eval "$check"; then return 0; fi
    sleep 2
  done
  return 1
}

stop_all() {
  curl -sf -X POST http://127.0.0.1:8091/api/fl/stop -H 'Content-Type: application/json' -d '{}' >/dev/null || true
  sleep 2
}

run_scenario() {
  local scenario="$1"
  curl -sf -X POST http://127.0.0.1:8091/api/fl/stop -H 'Content-Type: application/json' -d '{}' >/dev/null || true
  sleep 2
  curl -sf -X POST http://127.0.0.1:8091/api/fl/start \
    -H 'Content-Type: application/json' \
    -d "{\"fl_rounds\":\"2\",\"fl_scenario\":\"${scenario}\",\"fl_port\":\"8087\",\"fl_dashboard_port\":\"8090\"}" >/dev/null
  sleep 3
  docker exec iotronic-ui python2.7 -c "
import json, time, urllib2
from iotronicclient.v1 import client as ic
scenario = '${scenario}'
plugin = 'fl-client-pm' if scenario == 'pm' else 'fl-client-heart'
csv_map = {
  'heart': {'board-alpha':'/opt/fl/heart_1.csv','board-beta':'/opt/fl/heart_2.csv','board-gamma':'/opt/fl/heart_3.csv'},
  'pm': {'board-alpha':'/opt/fl/machine_1.csv','board-beta':'/opt/fl/machine_2.csv','board-gamma':'/opt/fl/machine_3.csv'},
}
body = json.dumps({'auth': {'identity': {'methods': ['password'], 'password': {'user': {'name': 'admin', 'domain': {'name': 'Default'}, 'password': 's4t'}}}, 'scope': {'project': {'name': 'admin', 'domain': {'name': 'Default'}}}}})
r = urllib2.urlopen(urllib2.Request('http://keystone:5000/v3/auth/tokens', body, {'Content-Type': 'application/json'}))
token = r.info().get('X-Subject-Token')
c = ic.Client(token=token, endpoint='http://iotronic-conductor:8812/v1/')
plugins = {p.name: p.uuid for p in c.plugin.list(all_plugins=True)}
boards = {b.name: b.uuid for b in c.board.list() if b.status=='online' and b.name.startswith('board-')}
pm, heart = plugins.get('fl-client-pm',''), plugins.get('fl-client-heart','')
order = ['board-beta','board-gamma','board-alpha']
for name in order:
    bid = boards[name]
    for pid in (heart, pm):
        if pid:
            try: c.plugin_injection.plugin_action(bid, pid, 'PluginStop', {})
            except: pass
time.sleep(2)
pid = plugins[plugin]
csv = csv_map[scenario]
for i, name in enumerate(order):
    bid = boards[name]
    params = {'board_name': name, 'csv_file': csv[name], 'server_address': 'fl-control:8087', 'dashboard_url': 'http://fl-control:8090', 'fl_scenario': scenario}
    time.sleep(2.0 if i == 0 else 0.8)
    c.plugin_injection.plugin_action(bid, pid, 'PluginStart', params)
" >/dev/null
}

echo "=== FL workflow tests ==="

echo "[1] Stop server"
stop_all
if curl -sf http://127.0.0.1:8091/api/fl/status | python3 -c "import json,sys; s=json.load(sys.stdin); sys.exit(0 if not s.get('running') else 1)"; then
  ok "server stopped"
else
  bad "server still running after stop"
fi

echo "[2] Heart scenario (2 rounds)"
run_scenario heart
if wait_state 40 "curl -sf http://127.0.0.1:8090/api/state | python3 -c \"import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get('fl_scenario')=='heart' and len(s.get('accuracy',[]))>=2 else 1)\""; then
  ok "heart metrics after rounds"
else
  bad "heart metrics missing"
fi

echo "[3] PM scenario switch (2 rounds)"
run_scenario pm
if wait_state 40 "curl -sf http://127.0.0.1:8090/api/state | python3 -c \"import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get('fl_scenario')=='pm' and len(s.get('accuracy',[]))>=2 else 1)\""; then
  ok "PM metrics after rounds"
else
  curl -sf http://127.0.0.1:8090/api/state | python3 -c "import json,sys; s=json.load(sys.stdin); print('  debug scenario',s.get('fl_scenario'),'acc',len(s.get('accuracy',[])),'phase',s.get('phase'))" || true
  bad "PM metrics missing"
fi

echo "[4] Clients use correct CSV"
curl -sf http://127.0.0.1:8090/api/state | python3 -c "
import json, sys
s = json.load(sys.stdin)
clients = s.get('clients', {})
ok_pm = all('machine_' in (clients.get(b, {}).get('csv_file') or '') for b in ('board-alpha','board-beta','board-gamma'))
sys.exit(0 if ok_pm else 1)
" && ok "all boards on machine_*.csv" || bad "wrong CSV on boards"

echo "[5] Horizon FL page loads"
code=$(curl -s -o /dev/null -w '%{http_code}' -L -b /tmp/fl-cookie -c /tmp/fl-cookie \
  -d 'username=admin&password=s4t' http://127.0.0.1/horizon/auth/login/ 2>/dev/null || echo 000)
# Try without auth - panel may redirect
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/horizon/iot/federated_learning/ 2>/dev/null || echo 000)
if [[ "$code" == "200" || "$code" == "302" ]]; then
  ok "Horizon FL panel HTTP $code"
else
  bad "Horizon FL panel HTTP $code"
fi

echo "=== Results: $PASS passed, $FAIL failed ==="
exit $(( FAIL > 0 ? 1 : 0 ))
