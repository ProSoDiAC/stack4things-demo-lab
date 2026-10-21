#!/usr/bin/env bash
# Weather station thing (vendor/ch14/weather_web_server.py) exposed via WSTUN
# Book uses port 8080 on physical boards; LR compose image reserves :8080 — lab default 8088.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="${S4T_LAB_HOST:-$(cat "$ROOT/vm-ip.txt")}"
BOARD="${S4T_BOARD:-board-alpha}"
SERVICE_NAME="${S4T_WEATHER_SERVICE:-weather-wot}"
LOCAL_PORT="${S4T_WEATHER_PORT:-8088}"
WEATHER_SRC="${ROOT}/vendor/ch14/weather_web_server.py"
STATE="${ROOT}/experiments/webservices/weather-state.json"

echo "=== Weather demo — port ${LOCAL_PORT} ==="

[[ -f "$WEATHER_SRC" ]] || { echo "FAIL: missing $WEATHER_SRC"; exit 1; }
docker ps --format '{{.Names}}' | grep -qx lightning-rod || { echo "FAIL: lightning-rod not running"; exit 1; }

docker cp "$WEATHER_SRC" lightning-rod:/tmp/weather_web_server.py
if ! docker exec lightning-rod sh -c "curl -sf --connect-timeout 2 http://127.0.0.1:${LOCAL_PORT}/sensors >/dev/null 2>&1"; then
  docker exec -d lightning-rod sh -c "nohup python3 /tmp/weather_web_server.py ${LOCAL_PORT} >/tmp/weather.log 2>&1 &"
  sleep 3
fi

CODE=$(docker exec lightning-rod sh -c "curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 http://127.0.0.1:${LOCAL_PORT}/sensors" || echo "000")
[[ "$CODE" == "200" ]] || { echo "FAIL: LR internal /sensors HTTP ${CODE}"; docker exec lightning-rod cat /tmp/weather.log 2>/dev/null || true; exit 1; }
echo "OK weather_web_server inside LR :${LOCAL_PORT}/sensors → HTTP ${CODE}"

export HOST BOARD SERVICE_NAME LOCAL_PORT STATE
python3 <<'PY'
import json, os, sys, time, urllib.request, urllib.error, subprocess

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
bl = json.loads(boards)
if isinstance(bl, dict):
    bl = bl.get("boards", [])
bid = next((b["uuid"] for b in bl if b.get("name") == BOARD), None)
if not bid:
    print(f"FAIL board {BOARD} not found"); sys.exit(1)

_, sl = api(t, "GET", "/v1/services/")
services = {s["uuid"]: s for s in json.loads(sl).get("services", [])}
svc_id = None
for s in services.values():
    if s.get("name") == SERVICE:
        svc_id = s["uuid"]
        if int(s.get("port") or 0) != LOCAL_PORT:
            api(t, "DELETE", f"/v1/services/{svc_id}")
            svc_id = None
        break
if not svc_id:
    code, body = api(t, "POST", "/v1/services", {"name": SERVICE, "port": LOCAL_PORT, "protocol": "TCP"})
    if code not in (200, 201):
        print(f"FAIL create service HTTP {code}: {body}"); sys.exit(1)
    svc_id = json.loads(body)["uuid"]
    services[svc_id] = json.loads(body)
    print(f"CREATED service {SERVICE} port={LOCAL_PORT}")

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

url = f"http://{HOST}:{pub}/sensors"
hc = subprocess.check_output(
    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "8", url], text=True
).strip()
ok = hc == "200"
print(f"{'OK' if ok else 'FAIL'} {url} → HTTP {hc}")
with open(STATE, "w") as f:
    json.dump({
        "host": HOST, "board": BOARD, "service": SERVICE,
        "book_port": 8080, "lab_port": LOCAL_PORT,
        "cloud_port": pub, "verified": ok,
    }, f, indent=2)
sys.exit(0 if ok else 1)
PY

echo "State written to ${STATE}"
