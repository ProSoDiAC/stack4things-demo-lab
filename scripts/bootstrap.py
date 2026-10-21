#!/usr/bin/env python3
"""Populate a fresh Stack4Things lab: boards, plugins, metrics stream, web services, FL.

Idempotent: safe to re-run at any time (existing objects are detected and skipped).
Only needs the docker CLI and the Python 3 standard library on the host.

  ./lab bootstrap            # everything
  ./lab bootstrap --only boards plugins
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = os.environ.get("S4T_API_HOST", "127.0.0.1")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "s4t")
LR_USER = os.environ.get("S4T_LR_USER", "me")
LR_PASS = os.environ.get("S4T_LR_PASS", "arancino")
WAMP_URL = "wss://crossbar:8181/"

# name, registration code, host port of the Lightning-Rod dashboard, container
BOARDS = [
    ("board-alpha", "board-alpha-lab2026", 1474, "lightning-rod"),
    ("board-beta", "board-beta-lab2026", 1475, "lightning-rod-2"),
    ("board-gamma", "board-gamma-lab2026", 1476, "lightning-rod-3"),
    ("board-delta", "board-delta-lab2026", 1477, "lightning-rod-4"),
    ("board-epsilon", "board-epsilon-lab2026", 1478, "lightning-rod-5"),
    ("board-zeta", "board-zeta-lab2026", 1479, "lightning-rod-6"),
]

STEPS = ["boards", "plugins", "fl", "metrics", "services", "verify"]


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], timeout: int = 900, check: bool = True, **kw) -> subprocess.CompletedProcess:
    log("  $ " + " ".join(cmd))
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, cwd=ROOT, **kw)
    if check and cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "")[-800:]
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{tail}")
    return cp


# ----------------------------------------------------------------------------- REST helpers
def keystone_token() -> str:
    body = json.dumps({"auth": {
        "identity": {"methods": ["password"], "password": {"user": {
            "name": "admin", "domain": {"name": "Default"}, "password": ADMIN_PASS}}},
        "scope": {"project": {"name": "admin", "domain": {"name": "Default"}}},
    }}).encode()
    req = urllib.request.Request(f"http://{API}:5000/v3/auth/tokens", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.headers["X-Subject-Token"]


def api(token: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://{API}:8812{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Auth-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def list_boards(token: str) -> list[dict]:
    code, body = api(token, "GET", "/v1/boards/")
    if code != 200:
        raise RuntimeError(f"cannot list boards: HTTP {code} {body[:200]}")
    data = json.loads(body)
    return data.get("boards", []) if isinstance(data, dict) else data


def wait_control_plane(timeout: int = 300) -> str:
    log("Waiting for Keystone + Conductor ...")
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            token = keystone_token()
            list_boards(token)
            log("  control plane ready")
            return token
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(5)
    raise RuntimeError(f"control plane not ready: {last}")


# ----------------------------------------------------------------------------- boards
def ensure_board(token: str, name: str, code: str) -> dict:
    for b in list_boards(token):
        if b.get("name") == name:
            return b
    payload = {"name": name, "code": code, "type": "virtual",
               "location": [{"latitude": "38.19", "longitude": "15.55", "altitude": "0"}]}
    status, body = api(token, "POST", "/v1/boards/", payload)
    if status not in (200, 201):
        raise RuntimeError(f"create board {name}: HTTP {status} {body[:200]}")
    log(f"  created board {name}")
    return json.loads(body)


def configure_lr(port: int, code: str, name: str) -> None:
    """Submit the Lightning-Rod 'Config' form (what a human does in the LR web UI)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = f"http://127.0.0.1:{port}"

    def post(path: str, fields: dict) -> int:
        req = urllib.request.Request(base + path, data=urllib.parse.urlencode(fields).encode(), method="POST")
        try:
            return opener.open(req, timeout=60).status
        except urllib.error.HTTPError as exc:
            return exc.code

    post("/login", {"username": LR_USER, "password": LR_PASS})  # not needed on first boot, harmless
    status = post("/config", {"urlwagent": WAMP_URL, "code": code, "hostname": name,
                              "reg_btn": "CONFIGURE"})
    log(f"  LR :{port} config submitted for {name} (HTTP {status})")


def step_boards(token: str) -> None:
    log("\n== boards ==")
    for name, code, port, container in BOARDS:
        ensure_board(token, name, code)
    pending = []
    for name, code, port, container in BOARDS:
        board = next(b for b in list_boards(token) if b["name"] == name)
        if board.get("status") == "online":
            log(f"  {name} already online")
        else:
            configure_lr(port, code, name)
            pending.append(name)
    deadline = time.time() + 240
    while pending and time.time() < deadline:
        time.sleep(5)
        online = {b["name"] for b in list_boards(token) if b.get("status") == "online"}
        pending = [n for n in pending if n not in online]
    if pending:
        raise RuntimeError(f"boards still offline: {pending} (check: docker logs lightning-rod)")
    log("  all boards online")


# ----------------------------------------------------------------------------- plugins
PLUGIN_HELPER = r'''
import cPickle, json, os, sys, urllib2
name, path, callable_ = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
body = json.dumps({"auth": {"identity": {"methods": ["password"], "password": {"user": {
    "name": "admin", "domain": {"name": "Default"}, "password": os.environ.get("S4T_ADMIN_PASS", "s4t")}}},
    "scope": {"project": {"name": "admin", "domain": {"name": "Default"}}}}})
r = urllib2.urlopen(urllib2.Request("http://keystone:5000/v3/auth/tokens", body, {"Content-Type": "application/json"}))
token = r.info().get("X-Subject-Token")
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint="http://iotronic-conductor:8812/v1/")
code = open(path).read().decode("utf-8").encode("ascii", "replace")
plugins = dict((p.name, p.uuid) for p in c.plugin.list(all_plugins=True))
if name in plugins:
    c.plugin.update(plugins[name], {"name": name, "public": True, "callable": callable_,
                                    "code": cPickle.dumps(str(code)), "parameters": {}})
    print("updated " + name)
else:
    p = c.plugin.create(name=name, public=True, callable=callable_, code=str(code), parameters={})
    print("created " + name + " " + p.uuid)
'''


def ensure_plugin(name: str, source: Path, callable_: bool) -> None:
    run(["docker", "cp", str(source), f"iotronic-ui:/tmp/plugin-{name}.py"])
    cp = run(["docker", "exec", "-e", f"S4T_ADMIN_PASS={ADMIN_PASS}", "iotronic-ui", "python2.7", "-c",
              PLUGIN_HELPER, name, f"/tmp/plugin-{name}.py", "1" if callable_ else "0"])
    log("  " + (cp.stdout.strip().splitlines() or ["?"])[-1])


def step_plugins(token: str) -> None:
    log("\n== plugins ==")
    ensure_plugin("HelloName", ROOT / "plugins" / "hello_name.py", True)
    ensure_plugin("EnvironmentalDemo", ROOT / "plugins" / "environmental_demo.py", False)


# ----------------------------------------------------------------------------- the rest delegates to the demo scripts
def step_fl(token: str) -> None:
    log("\n== federated learning (python deps on boards + client plugins) ==")
    run(["bash", "experiments/federated-learning/install-fl-on-boards.sh"], timeout=3600)
    run(["bash", "experiments/federated-learning/setup-fl-demo-plugins.sh"])
    run(["docker", "restart", "fl-control"], check=False)


def step_metrics(token: str) -> None:
    log("\n== metrics (EnvironmentalDemo -> metrics-gateway -> InfluxDB -> Grafana) ==")
    run(["python3", "experiments/metrics/setup-metrics-demo.py"], timeout=600)


def step_services(token: str) -> None:
    log("\n== web services over WSTUN ==")
    for script in ("experiments/webservices/run-weather-demo.sh",
                   "experiments/webservices/run-wot-fritzing-demo.sh",
                   "experiments/webservices/run-ssh-service.sh"):
        run(["bash", script], timeout=600)
    run(["python3", "experiments/webservices/setup-wstun-demo.py"], timeout=600, check=False)


def step_verify(token: str) -> None:
    log("\n== verify ==")
    cp = subprocess.run(["python3", "scripts/verify-demo.py"], cwd=ROOT)
    if cp.returncode != 0:
        raise RuntimeError("verify-demo reports NOT READY")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=STEPS, help="run only these steps")
    args = ap.parse_args()
    steps = args.only or STEPS
    os.environ.setdefault("S4T_LAB_HOST", "127.0.0.1")
    token = wait_control_plane()
    funcs = {"boards": step_boards, "plugins": step_plugins, "fl": step_fl,
             "metrics": step_metrics, "services": step_services, "verify": step_verify}
    for step in steps:
        funcs[step](token)
    log("\nBootstrap complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nBOOTSTRAP FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
