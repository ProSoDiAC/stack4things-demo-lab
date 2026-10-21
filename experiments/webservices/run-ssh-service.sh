#!/usr/bin/env bash
# run-ssh-service.sh — Install sshd on all Lightning Rod containers and
# expose SSH (port 22) as a Stack4Things service on each board.
# SSH credentials: root / arancino
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="${S4T_LAB_HOST:-$(cat "$ROOT/vm-ip.txt")}"

echo "=== SSH WoT service setup — all boards ==="
echo "    Host: $HOST"
echo ""

# ── 1. Install & configure sshd inside every LR container ──────────────────
echo "--- Step 1: install/configure sshd on all containers ---"
for C in lightning-rod lightning-rod-2 lightning-rod-3 lightning-rod-4 lightning-rod-5 lightning-rod-6; do
  docker ps --format '{{.Names}}' | grep -qx "$C" || { echo "  SKIP $C (not running)"; continue; }
  docker exec "$C" sh -c '
    echo "deb http://archive.debian.org/debian buster main contrib non-free" > /etc/apt/sources.list
    echo "deb http://archive.debian.org/debian-security buster/updates main contrib non-free" >> /etc/apt/sources.list
    which sshd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq openssh-server)
    echo "root:arancino" | chpasswd
    mkdir -p /run/sshd
    sed -i "s/^#*PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config
    sed -i "s/^#*PasswordAuthentication.*/PasswordAuthentication yes/" /etc/ssh/sshd_config
    grep -q "^PermitRootLogin" /etc/ssh/sshd_config || echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
    grep -q "^PasswordAuthentication" /etc/ssh/sshd_config || echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
    ssh-keygen -A 2>/dev/null
    pkill sshd 2>/dev/null || true
    sleep 1
    /usr/sbin/sshd
  ' 2>&1 | grep -v "^$" | sed "s/^/  [$C] /" || true
  echo "  ✓ $C: sshd running (root:arancino)"
done

# ── 2. S4T: register service + enable on each board ─────────────────────────
echo ""
echo "--- Step 2: S4T service registration & enablement ---"
export HOST ROOT
python3 <<'PY'
import json, os, sys, time, subprocess
import urllib.request, urllib.error

HOST = os.environ["HOST"]
ROOT = os.environ["ROOT"]
SSH_SERVICE = "ssh-remote"
SSH_PORT = 22

BOARD_CONTAINER = {
    "board-alpha":   "lightning-rod",
    "board-beta":    "lightning-rod-2",
    "board-gamma":   "lightning-rod-3",
    "board-delta":   "lightning-rod-4",
    "board-epsilon": "lightning-rod-5",
    "board-zeta":    "lightning-rod-6",
}

def api_call(token, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:8812{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "X-Auth-Token": token}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}

# Auth
body = json.dumps({"auth":{"identity":{"methods":["password"],"password":{"user":{
    "name":"admin","domain":{"name":"Default"},"password":"s4t"}}},
    "scope":{"project":{"name":"admin","domain":{"name":"Default"}}}}}).encode()
req = urllib.request.Request(f"http://127.0.0.1:5000/v3/auth/tokens",
    data=body, headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=20) as r:
    token = r.headers["X-Subject-Token"]
print(f"  ✓ token: {token[:30]}...")

# Ensure catalog service
_, svcs = api_call(token, "GET", "/v1/services/")
svc_id = None
for s in svcs.get("services", []):
    if s.get("name") == SSH_SERVICE and int(s.get("port", 0)) == SSH_PORT:
        svc_id = s["uuid"]
        break
if not svc_id:
    code, resp = api_call(token, "POST", "/v1/services/",
        {"name": SSH_SERVICE, "port": SSH_PORT, "protocol": "TCP"})
    svc_id = resp.get("uuid", "")
    print(f"  ✓ Created catalog service '{SSH_SERVICE}' uuid={svc_id}")
else:
    print(f"  ✓ Catalog service '{SSH_SERVICE}' already exists uuid={svc_id}")

# Get boards
_, bl = api_call(token, "GET", "/v1/boards/")
boards = {b["name"]: b["uuid"] for b in bl.get("boards", [])}

results = {}
for board, container in BOARD_CONTAINER.items():
    uuid = boards.get(board)
    if not uuid:
        print(f"  SKIP {board} (not in S4T)")
        continue
    # Check if container running
    rc = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True, text=True).stdout.strip()
    if rc != "true":
        print(f"  SKIP {container} (not running)")
        continue

    print(f"  {board} → {container}: enabling {SSH_SERVICE}...", end=" ", flush=True)
    api_call(token, "POST", f"/v1/boards/{uuid}/services/{SSH_SERVICE}/action",
        {"action": "ServiceEnable"})
    time.sleep(4)

    _, exposed = api_call(token, "GET", f"/v1/boards/{uuid}/services/")
    pub = 0
    for item in exposed.get("exposed", []):
        if item.get("service") == svc_id:
            pub = int(item.get("public_port") or 0)
            break
    if pub:
        print(f"✓ public port {pub}")
        print(f"     → ssh root@{HOST} -p {pub}   (pw: arancino)")
        results[board] = pub
    else:
        print("⚠ no public port yet")
        results[board] = 0

# Write state
state = {
    "host": HOST, "service": SSH_SERVICE, "local_port": SSH_PORT,
    "credentials": {"user": "root", "password": "arancino"},
    "boards": {
        b: {"public_port": p, "ssh_cmd": f"ssh root@{HOST} -p {p}"}
        for b, p in results.items() if p > 0
    }
}
sf = f"{ROOT}/experiments/webservices/ssh-state.json"
with open(sf, "w") as f:
    json.dump(state, f, indent=2)
print(f"\n  State written to {sf}")
print("\n=== Summary ===")
for b, info in state["boards"].items():
    print(f"  {b}: {info['ssh_cmd']}  (password: arancino)")
PY

echo ""
echo "=== Done ==="
