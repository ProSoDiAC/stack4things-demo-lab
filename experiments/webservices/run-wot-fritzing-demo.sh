#!/usr/bin/env bash
# WoT Fritzing demo — nginx (8090) + LED API (8091) on Lightning Rod, WSTUN expose.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEMO="$(cd "$(dirname "$0")" && pwd)"
FRITZING="${DEMO}/wot-fritzing"
HOST="${S4T_LAB_HOST:-$(cat "$ROOT/vm-ip.txt")}"
BOARD="${S4T_BOARD:-board-alpha}"
SERVICE_NAME="${S4T_WOT_FRITZING_SERVICE:-wot-fritzing}"
LOCAL_PORT="${S4T_WOT_FRITZING_PORT:-8090}"
API_PORT=8091
LR="${S4T_LR_CONTAINER:-lightning-rod}"
STATE="${FRITZING}/wot-fritzing-state.json"

echo "=== WoT Fritzing demo — nginx :${LOCAL_PORT} on ${LR} ==="

docker ps --format '{{.Names}}' | grep -qx "$LR" || { echo "FAIL: $LR not running"; exit 1; }

# The LR entrypoint (entrypoints/lr-helpers.sh) already installs the site and starts the API on
# board-alpha; only (re)deploy by hand if it is not answering (e.g. LR started without LAB_DEMO_SERVICES).
if ! docker exec "$LR" sh -c "curl -sf http://127.0.0.1:${API_PORT}/api/circuit >/dev/null"; then
  docker exec "$LR" mkdir -p /var/www/wot-fritzing /etc/nginx/sites-available /etc/nginx/sites-enabled
  docker cp "$FRITZING/www/index.html" "$LR:/var/www/wot-fritzing/index.html"
  docker cp "$FRITZING/wot_board_api.py" "$LR:/opt/wot_board_api.py"
  docker cp "$FRITZING/nginx-wot-fritzing.conf" "$LR:/etc/nginx/sites-available/wot-fritzing"
  docker exec "$LR" sh -c "
    ln -sf /etc/nginx/sites-available/wot-fritzing /etc/nginx/sites-enabled/wot-fritzing
    nohup python3 /opt/wot_board_api.py ${API_PORT} >/tmp/wot-board-api.log 2>&1 &
    sleep 2
    curl -sf http://127.0.0.1:${API_PORT}/api/circuit >/dev/null || { cat /tmp/wot-board-api.log; exit 1; }
    nginx -t && (nginx -s reload 2>/dev/null || nginx)
  "
fi

sleep 2
CODE=$(docker exec "$LR" sh -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${LOCAL_PORT}/" || echo "000")
[[ "$CODE" == "200" ]] || { echo "FAIL: nginx :${LOCAL_PORT} HTTP ${CODE}"; exit 1; }
CODE=$(docker exec "$LR" sh -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${LOCAL_PORT}/api/circuit" || echo "000")
[[ "$CODE" == "200" ]] || { echo "FAIL: WoT API via nginx HTTP ${CODE}"; exit 1; }
echo "OK Fritzing UI + WoT API inside ${LR}"

export HOST BOARD SERVICE_NAME LOCAL_PORT STATE
python3 <<'PY'
import json, os, sys, time, urllib.request, urllib.error

HOST = os.environ["HOST"]
BOARD = os.environ["BOARD"]
SERVICE = os.environ["SERVICE_NAME"]
LOCAL_PORT = int(os.environ["LOCAL_PORT"])
STATE = os.environ["STATE"]

def token():
    body = json.dumps({"auth":{"identity":{"methods":["password"],"password":{"user":{
        "name":"admin","domain":{"name":"Default"},"password":"s4t"}}},
        "scope":{"project":{"name":"admin","domain":{"name":"Default"}}}}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:5000/v3/auth/tokens", data=body,
        headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.headers["X-Subject-Token"]

def api(t, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:8812{path}", data=data,
        headers={"Content-Type":"application/json","X-Auth-Token":t}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

t = token()
_, boards = api(t, "GET", "/v1/boards/")
boards = json.loads(boards).get("boards", [])
bid = next(b["uuid"] for b in boards if b.get("name") == BOARD)

_, svcs = api(t, "GET", "/v1/services/")
services = {s["uuid"]: s for s in json.loads(svcs).get("services", [])}
svc_id = None
for uid, s in services.items():
    if s.get("name") == SERVICE:
        svc_id = uid
        if int(s.get("port") or 0) != LOCAL_PORT:
            api(t, "DELETE", f"/v1/services/{uid}")
            svc_id = None
        break
if not svc_id:
    code, body = api(t, "POST", "/v1/services", {
        "name": SERVICE, "port": LOCAL_PORT, "protocol": "TCP",
    })
    if code not in (200, 201):
        print(f"FAIL create service HTTP {code}: {body}"); sys.exit(1)
    svc_id = json.loads(body)["uuid"]
    print(f"CREATED catalog service {SERVICE} port={LOCAL_PORT}")

code, body = api(t, "POST", f"/v1/boards/{bid}/services/{SERVICE}/action", {"action": "ServiceEnable"})
print(f"ServiceEnable HTTP {code}: {body[:120]}")
time.sleep(4)
_, exposed = api(t, "GET", f"/v1/boards/{bid}/services/")
pub = 0
for item in json.loads(exposed).get("exposed", []):
    if item.get("service") == svc_id:
        pub = int(item.get("public_port") or 0)
        break
if pub < 50001:
    print(f"FAIL no public_port: {exposed}"); sys.exit(1)

url = f"http://{HOST}:{pub}/"
import subprocess
hc = subprocess.check_output(
    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "10", url], text=True
).strip()
ok = hc == "200"
print(f"{'OK' if ok else 'FAIL'} {url} -> HTTP {hc}")
with open(STATE, "w") as f:
    json.dump({
        "host": HOST, "board": BOARD, "service": SERVICE,
        "local_port": LOCAL_PORT, "cloud_port": pub, "verified": ok,
    }, f, indent=2)
sys.exit(0 if ok else 1)
PY

echo "State written to ${STATE}"
echo "Open IoT -> Web Services (WoT) and select ${SERVICE_NAME}"
