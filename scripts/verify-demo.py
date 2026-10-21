#!/usr/bin/env python3
"""Verify Stack4Things lab demo readiness and optionally heal broken pieces.

Usage:
  ./scripts/verify-demo.py              # check + heal (default)
  ./scripts/verify-demo.py --check-only # report only
  ./scripts/verify-demo.py --heal       # explicit heal (same as default)
  ./scripts/verify-demo.py -q           # quieter summary

Exit codes: 0 = demo ready, 1 = still broken after heal/check, 2 = script error
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = str(ROOT / "docker-compose.yml")

CORE_CONTAINERS = [
    "keystone",
    "rabbitmq",
    "iotronic-db",
    "iotronic-conductor",
    "iotronic-wagent",
    "iotronic-wstun",
    "iotronic-ui",
    "crossbar",
    "lightning-rod",
    "lightning-rod-2",
    "lightning-rod-3",
    "lightning-rod-4",
    "lightning-rod-5",
    "lightning-rod-6",
    "influxdb",
    "grafana",
    "metrics-gateway",
    "fl-control",
    "lr-log-proxy",
]

STATIC_BOARDS = [
    "board-alpha",
    "board-beta",
    "board-gamma",
    "board-delta",
    "board-epsilon",
    "board-zeta",
]
LR_BY_BOARD = {
    "board-alpha": "lightning-rod",
    "board-beta": "lightning-rod-2",
    "board-gamma": "lightning-rod-3",
    "board-delta": "lightning-rod-4",
    "board-epsilon": "lightning-rod-5",
    "board-zeta": "lightning-rod-6",
}
FL_BOARDS = ["board-alpha", "board-beta", "board-gamma"]
REQUIRED_PLUGINS = [
    "HelloName",
    "EnvironmentalDemo",
    "fl-client-heart",
    "fl-client-pm",
]
WEB_SERVICES = [
    "lr-nginx-demo",
    "wot-fritzing",
    "weather-wot",
    "ssh-remote",
]

HOST = os.environ.get("S4T_LAB_HOST")
if not HOST:
    tip = ROOT / "vm-ip.txt"
    HOST = tip.read_text().strip() if tip.is_file() else "127.0.0.1"

METRICS_URL = os.environ.get("S4T_METRICS_URL", "http://127.0.0.1:8093")
FL_CONTROL_URL = os.environ.get("S4T_FL_CONTROL_URL", "http://127.0.0.1:8091")
FL_DASH_URL = os.environ.get("S4T_FL_DASH_URL", "http://127.0.0.1:8090")
LR_PROXY_URL = os.environ.get("S4T_LR_PROXY_URL", "http://127.0.0.1:8092")
HORIZON_URL = os.environ.get("S4T_HORIZON_URL", f"http://{HOST}/horizon/")


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)
    healed: list[str] = field(default_factory=list)

    def add_ok(self, msg: str) -> None:
        self.ok.append(msg)

    def add_warn(self, msg: str) -> None:
        self.warn.append(msg)

    def add_fail(self, msg: str) -> None:
        self.fail.append(msg)

    def add_healed(self, msg: str) -> None:
        self.healed.append(msg)


def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def run(
    cmd: list[str],
    timeout: int = 120,
    check: bool = False,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
        cwd=str(cwd) if cwd else None,
    )


def http_json(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 15,
) -> tuple[int | None, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw
    except Exception as exc:
        return None, str(exc)


def http_code(url: str, timeout: int = 8) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0


def docker_ps_names() -> dict[str, str]:
    """name -> status string."""
    cp = run(
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        timeout=30,
    )
    out: dict[str, str] = {}
    for line in (cp.stdout or "").splitlines():
        if "\t" not in line:
            continue
        name, status = line.split("\t", 1)
        out[name.strip()] = status.strip()
    return out


def compose_up(services: list[str], quiet: bool) -> bool:
    if not services:
        return True
    cmd = [
        "docker",
        "compose",
        "-f",
        COMPOSE_FILE,
        "up",
        "-d",
        *services,
    ]
    log(f"  -> compose up {' '.join(services)}", quiet)
    cp = run(cmd, timeout=300, cwd=ROOT)
    if cp.returncode != 0:
        log((cp.stderr or cp.stdout or "")[-500:], quiet)
        return False
    return True


def docker_restart(name: str, quiet: bool) -> bool:
    log(f"  -> docker restart {name}", quiet)
    cp = run(["docker", "restart", name], timeout=120)
    return cp.returncode == 0


def docker_start(name: str, quiet: bool) -> bool:
    log(f"  -> docker start {name}", quiet)
    cp = run(["docker", "start", name], timeout=120)
    return cp.returncode == 0


IOT_HELPER = r'''
import json, os, sys, urllib2, time
action = sys.argv[1]
body = json.dumps({
  "auth": {
    "identity": {
      "methods": ["password"],
      "password": {
        "user": {
          "name": "admin",
          "domain": {"name": "Default"},
          "password": os.environ.get("S4T_ADMIN_PASS", "s4t")
        }
      }
    },
    "scope": {
      "project": {
        "name": "admin",
        "domain": {"name": "Default"}
      }
    }
  }
})
r = urllib2.urlopen(urllib2.Request(
  "http://keystone:5000/v3/auth/tokens", body,
  {"Content-Type": "application/json"}
))
token = r.info().get("X-Subject-Token")
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint="http://iotronic-conductor:8812/v1/")

def out(obj):
  print(json.dumps(obj))

if action == "boards":
  out([{"name": b.name, "uuid": b.uuid, "status": getattr(b, "status", None)}
       for b in c.board.list()])
elif action == "plugins":
  out([{"name": p.name, "uuid": p.uuid, "callable": getattr(p, "callable", None)}
       for p in c.plugin.list(all_plugins=True)])
elif action == "list_web":
  boards = dict((b.name, b) for b in c.board.list())
  alpha = boards.get("board-alpha")
  if not alpha:
    out({"ok": False, "error": "board-alpha missing", "exposed": []})
    sys.exit(0)
  req = urllib2.Request(
    "http://iotronic-conductor:8812/v1/boards/%s/services/" % alpha.uuid,
    headers={"X-Auth-Token": token}
  )
  exposed = json.loads(urllib2.urlopen(req, timeout=20).read()).get("exposed", [])
  out({"ok": True, "exposed": exposed})
elif action == "ensure_web":
  boards = dict((b.name, b) for b in c.board.list())
  services = dict((s.name, s) for s in c.service.list())
  alpha = boards.get("board-alpha")
  if not alpha:
    out({"ok": False, "error": "board-alpha missing"})
    sys.exit(0)
  results = []
  for name in ["lr-nginx-demo", "wot-fritzing", "weather-wot", "ssh-remote"]:
    if name not in services:
      results.append({"name": name, "ok": False, "error": "service missing"})
      continue
    path = "/v1/boards/%s/services/%s/action" % (alpha.uuid, name)
    data = json.dumps({"action": "ServiceEnable"})
    req = urllib2.Request(
      "http://iotronic-conductor:8812" + path, data=data,
      headers={"X-Auth-Token": token, "Content-Type": "application/json"}
    )
    try:
      resp = urllib2.urlopen(req, timeout=45)
      results.append({"name": name, "ok": True, "code": resp.getcode(),
                      "body": resp.read()[:200]})
    except urllib2.HTTPError as e:
      body = e.read()
      ok = (e.code in (200, 201)) or ("AlreadyExposed" in body)
      results.append({"name": name, "ok": ok, "code": e.code, "body": body[:200]})
  req = urllib2.Request(
    "http://iotronic-conductor:8812/v1/boards/%s/services/" % alpha.uuid,
    headers={"X-Auth-Token": token}
  )
  exposed = json.loads(urllib2.urlopen(req, timeout=20).read()).get("exposed", [])
  out({"ok": True, "results": results, "exposed": exposed})
elif action == "ensure_env_metrics":
  boards = dict((b.name, b) for b in c.board.list())
  plugins = dict((p.name, p) for p in c.plugin.list(all_plugins=True))
  alpha = boards.get("board-alpha")
  envp = plugins.get("EnvironmentalDemo")
  if not alpha or not envp:
    out({"ok": False, "error": "board or plugin missing"})
    sys.exit(0)
  try:
    c.plugin_injection.plugin_inject(alpha.uuid, envp.uuid, True)
  except Exception:
    pass
  out({"ok": True, "board": alpha.uuid, "plugin": envp.uuid,
       "name": alpha.name, "plugin_name": envp.name})
elif action == "start_env":
  board_uuid = sys.argv[2]
  plugin_uuid = sys.argv[3]
  params = json.loads(sys.argv[4])
  try:
    c.plugin_injection.plugin_action(board_uuid, plugin_uuid, "PluginStop", {})
  except Exception:
    pass
  time.sleep(1)
  res = c.plugin_injection.plugin_action(
    board_uuid, plugin_uuid, "PluginStart", params
  )
  out({"ok": True, "result": unicode(res)})
elif action == "hello_smoke":
  boards = dict((b.name, b) for b in c.board.list())
  plugins = dict((p.name, p) for p in c.plugin.list(all_plugins=True))
  alpha = boards["board-alpha"]
  hello = plugins["HelloName"]
  try:
    c.plugin_injection.plugin_inject(alpha.uuid, hello.uuid, False)
  except Exception:
    pass
  res = c.plugin_injection.plugin_action(
    alpha.uuid, hello.uuid, "PluginCall", {"name": "DemoCheck"}
  )
  out({"ok": True, "result": unicode(res)})
else:
  out({"ok": False, "error": "unknown action"})
'''


def iot(action: str, *args: str, quiet: bool = False) -> Any:
    """Run IoTronic helper inside iotronic-ui (has keystone + client)."""
    cmd = [
        "docker",
        "exec",
        "-i",
        "-e",
        "S4T_ADMIN_PASS=" + os.environ.get("ADMIN_PASS", "s4t"),
        "iotronic-ui",
        "python2.7",
        "-c",
        IOT_HELPER,
        action,
        *args,
    ]
    cp = run(cmd, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(
            "iot helper failed ({0}): {1}".format(
                action, (cp.stderr or cp.stdout or "")[-400:]
            )
        )
    text = (cp.stdout or "").strip().splitlines()
    if not text:
        raise RuntimeError("iot helper empty output for " + action)
    return json.loads(text[-1])


def ensure_containers(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Containers ===", quiet)
    status = docker_ps_names()
    missing = []
    stopped = []
    for name in CORE_CONTAINERS:
        st = status.get(name)
        if not st:
            missing.append(name)
            rep.add_fail(f"container missing: {name}")
        elif st.lower().startswith("up"):
            rep.add_ok(f"container up: {name}")
        else:
            stopped.append(name)
            rep.add_fail(f"container not running: {name} ({st})")

    if not heal:
        return
    for name in stopped:
        if docker_start(name, quiet) or docker_restart(name, quiet):
            rep.add_healed(f"started {name}")
            # remove matching fail
            rep.fail = [f for f in rep.fail if name not in f]
            rep.add_ok(f"container up: {name} (healed)")
    if missing:
        # map lightning-rod-* and core services via compose
        if compose_up(missing, quiet):
            rep.add_healed(f"compose up: {', '.join(missing)}")
            status2 = docker_ps_names()
            for name in list(missing):
                st = status2.get(name, "")
                if st.lower().startswith("up"):
                    rep.fail = [f for f in rep.fail if name not in f]
                    rep.add_ok(f"container up: {name} (healed)")


def ensure_http_endpoints(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== HTTP endpoints ===", quiet)
    checks = [
        ("Horizon", HORIZON_URL, None),
        ("metrics-gateway health", f"{METRICS_URL}/health", "metrics-gateway"),
        ("FL control status", f"{FL_CONTROL_URL}/api/fl/status", "fl-control"),
        ("FL live dashboard", f"{FL_DASH_URL}/", "fl-control"),
        ("LR log proxy", f"{LR_PROXY_URL}/provision/status", "lr-log-proxy"),
        ("Grafana", "http://127.0.0.1:3000/login", "grafana"),
    ]
    for label, url, service in checks:
        code = http_code(url)
        # Horizon 302 login is fine; Grafana 301/200 fine
        good = code in (200, 301, 302)
        if good:
            rep.add_ok(f"{label} HTTP {code}")
        else:
            rep.add_fail(f"{label} HTTP {code} ({url})")
            if heal and service:
                if docker_restart(service, quiet):
                    time.sleep(3)
                    code2 = http_code(url)
                    if code2 in (200, 301, 302):
                        rep.add_healed(f"restarted {service} -> HTTP {code2}")
                        rep.fail = [f for f in rep.fail if label not in f]
                        rep.add_ok(f"{label} HTTP {code2} (healed)")


def ensure_boards(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Boards ===", quiet)
    try:
        boards = iot("boards", quiet=quiet)
    except Exception as exc:
        rep.add_fail(f"cannot list boards: {exc}")
        if heal:
            docker_restart("iotronic-conductor", quiet)
            docker_restart("iotronic-wagent", quiet)
            time.sleep(8)
            try:
                boards = iot("boards", quiet=quiet)
                rep.add_healed("relisted boards after conductor/wagent restart")
            except Exception as exc2:
                rep.add_fail(f"boards still unavailable: {exc2}")
                return
        else:
            return

    by_name = {b["name"]: b for b in boards}
    for name in STATIC_BOARDS:
        b = by_name.get(name)
        if not b:
            rep.add_fail(f"board missing: {name}")
            continue
        st = (b.get("status") or "").lower()
        if st == "online":
            rep.add_ok(f"{name} online")
        else:
            rep.add_fail(f"{name} status={st}")
            if heal:
                lr = LR_BY_BOARD.get(name)
                if lr and docker_restart(lr, quiet):
                    rep.add_healed(f"restarted {lr} for {name}")
                    time.sleep(8)
                    boards2 = iot("boards", quiet=quiet)
                    b2 = next((x for x in boards2 if x["name"] == name), None)
                    if b2 and (b2.get("status") or "").lower() == "online":
                        rep.fail = [f for f in rep.fail if name not in f]
                        rep.add_ok(f"{name} online (healed)")


def ensure_plugins(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Plugins catalog ===", quiet)
    try:
        plugins = iot("plugins", quiet=quiet)
    except Exception as exc:
        rep.add_fail(f"cannot list plugins: {exc}")
        return
    names = {p["name"] for p in plugins}
    for name in REQUIRED_PLUGINS:
        if name in names:
            rep.add_ok(f"plugin present: {name}")
        else:
            rep.add_fail(f"plugin missing: {name}")
            if heal:
                rep.add_warn(
                    f"cannot auto-create {name}; register it from Horizon Plugins IDE"
                )


def ensure_metrics(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Metrics / EnvironmentalDemo ===", quiet)
    code, health = http_json(f"{METRICS_URL}/health")
    if code == 200 and isinstance(health, dict) and health.get("influx_ok"):
        rep.add_ok("metrics-gateway + Influx OK")
    else:
        rep.add_fail(f"metrics health bad: {health}")
        if heal and docker_restart("metrics-gateway", quiet):
            time.sleep(3)
            code, health = http_json(f"{METRICS_URL}/health")
            if code == 200 and isinstance(health, dict) and health.get("influx_ok"):
                rep.add_healed("metrics-gateway restarted")
                rep.fail = [f for f in rep.fail if "metrics health" not in f]
                rep.add_ok("metrics-gateway + Influx OK (healed)")

    code, active = http_json(f"{METRICS_URL}/v1/streams/active")
    live = 0
    if isinstance(active, dict):
        live = int(active.get("live_count") or 0)
    if live >= 1:
        rep.add_ok(f"live metrics streams: {live}")
        return

    rep.add_fail("no live metrics streams (EnvironmentalDemo not sending)")
    if not heal:
        return

    # Provision stream + start plugin on alpha
    try:
        meta = iot("ensure_env_metrics", quiet=quiet)
        if not meta.get("ok"):
            rep.add_warn(f"env metrics prep failed: {meta}")
            return
        prov_payload = {
            "board_uuid": meta["board"],
            "board_name": meta["name"],
            "plugin_uuid": meta["plugin"],
            "plugin_name": meta["plugin_name"],
            "measurement": "environmental_data",
            "field_schema": ["Temperature", "Humidity", "PM10", "PM25"],
        }
        pcode, prov = http_json(
            f"{METRICS_URL}/v1/streams/provision",
            method="POST",
            payload=prov_payload,
            timeout=30,
        )
        if pcode not in (200, 201) or not isinstance(prov, dict):
            rep.add_warn(f"stream provision failed: {pcode} {prov}")
            return
        params = {
            "metrics_url": prov.get("metrics_url")
            or f"http://metrics-gateway:8093/v1/metrics/write",
            "metrics_token": prov.get("metrics_token"),
            "metrics_stream": prov.get("metrics_stream") or "environmental_data",
        }
        if not params["metrics_token"]:
            rep.add_warn("provision returned no metrics_token")
            return
        start = iot(
            "start_env",
            meta["board"],
            meta["plugin"],
            json.dumps(params),
            quiet=quiet,
        )
        rep.add_healed(f"EnvironmentalDemo restarted with metrics ({start})")
        time.sleep(8)
        code, active = http_json(f"{METRICS_URL}/v1/streams/active")
        live = int(active.get("live_count") or 0) if isinstance(active, dict) else 0
        if live >= 1:
            rep.fail = [f for f in rep.fail if "live metrics" not in f]
            rep.add_ok(f"live metrics streams: {live} (healed)")
        else:
            rep.add_warn("EnvironmentalDemo started but stream not live yet")
    except Exception as exc:
        rep.add_warn(f"metrics heal error: {exc}")


def _ssh_banner(port: int) -> bool:
    """True if something answers with an SSH banner (SSH services are not HTTP)."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.settimeout(5)
            return sock.recv(16).startswith(b"SSH-")
    except OSError:
        return False


def ensure_webservices(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Web services (WSTUN) ===", quiet)
    data = None
    try:
        if heal:
            data = iot("ensure_web", quiet=quiet)
        else:
            data = iot("list_web", quiet=quiet)
    except Exception as exc:
        rep.add_fail(f"webservices check failed: {exc}")
        return

    exposed = data.get("exposed") or []
    if len(exposed) >= 3:
        rep.add_ok(f"exposed services on alpha: {len(exposed)}")
        if heal and data.get("results"):
            for r in data["results"]:
                if r.get("ok"):
                    rep.add_healed(f"ServiceEnable {r['name']}")
    else:
        rep.add_fail(f"few/no exposed services: {len(exposed)}")

    for item in exposed:
        pub = int(item.get("public_port") or 0)
        svc = item.get("service") or ""
        if pub >= 50001:
            code = http_code(f"http://127.0.0.1:{pub}/")
            if code in (200, 301, 302):
                rep.add_ok(f"WSTUN :{pub} HTTP {code}")
            elif _ssh_banner(pub):
                rep.add_ok(f"WSTUN :{pub} SSH banner")
            else:
                rep.add_warn(f"WSTUN :{pub} HTTP {code} (svc {svc[:8]})")


def ensure_fl(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Federated Learning ===", quiet)
    # deps on boards
    for board, container in [
        ("board-alpha", "lightning-rod"),
        ("board-beta", "lightning-rod-2"),
        ("board-gamma", "lightning-rod-3"),
    ]:
        cp = run(
            [
                "docker",
                "exec",
                container,
                "python3",
                "-c",
                "import flwr,os; print(flwr.__version__); print(os.path.isdir('/opt/fl'))",
            ],
            timeout=30,
        )
        if cp.returncode == 0 and "True" in (cp.stdout or ""):
            rep.add_ok(f"FL deps on {board} (flwr + /opt/fl)")
        else:
            rep.add_fail(f"FL deps missing on {board}")
            if heal:
                install = ROOT / "experiments" / "federated-learning" / "install-fl-on-boards.sh"
                if install.is_file():
                    log("  -> install-fl-on-boards.sh", quiet)
                    cp2 = run(["bash", str(install)], timeout=600)
                    if cp2.returncode == 0:
                        rep.add_healed("ran install-fl-on-boards.sh")
                        rep.fail = [f for f in rep.fail if "FL deps" not in f]
                        rep.add_ok(f"FL deps on {board} (healed attempt)")
                else:
                    rep.add_warn("install-fl-on-boards.sh not found")

    code, st = http_json(f"{FL_CONTROL_URL}/api/fl/status")
    running = isinstance(st, dict) and bool(st.get("running"))
    dash = isinstance(st, dict) and bool(st.get("dashboard_running"))
    if running:
        rep.add_ok("Flower server running")
    else:
        rep.add_fail("Flower server not running")
        if heal:
            body = {
                "fl_rounds": "2",
                "fl_port": 8087,
                "fl_dashboard_port": 8090,
            }
            scode, sres = http_json(
                f"{FL_CONTROL_URL}/api/fl/start",
                method="POST",
                payload=body,
                timeout=120,
            )
            if scode == 200 and isinstance(sres, dict) and sres.get("running"):
                rep.add_healed("started Flower server")
                rep.fail = [f for f in rep.fail if "Flower server" not in f]
                rep.add_ok("Flower server running (healed)")
            else:
                docker_restart("fl-control", quiet)
                time.sleep(3)
                scode, sres = http_json(
                    f"{FL_CONTROL_URL}/api/fl/start",
                    method="POST",
                    payload=body,
                    timeout=120,
                )
                if scode == 200 and isinstance(sres, dict) and sres.get("running"):
                    rep.add_healed("restarted fl-control + Flower server")
                    rep.fail = [f for f in rep.fail if "Flower server" not in f]
                    rep.add_ok("Flower server running (healed)")
                else:
                    rep.add_warn(f"FL start failed: {scode} {sres}")
    if dash or http_code(FL_DASH_URL) == 200:
        rep.add_ok("FL live dashboard reachable")
    else:
        rep.add_warn("FL live dashboard not reachable")


def ensure_hello_smoke(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== HelloName smoke ===", quiet)
    try:
        res = iot("hello_smoke", quiet=quiet)
        result = str(res.get("result") or "")
        if "Hello" in result:
            rep.add_ok(f"HelloName Call: {result}")
        else:
            rep.add_fail(f"HelloName unexpected: {result}")
    except Exception as exc:
        rep.add_fail(f"HelloName Call failed: {exc}")
        if heal:
            rep.add_warn("HelloName heal: inject/start from Horizon Plugins if needed")


def ensure_conductor_patch(rep: Report, heal: bool, quiet: bool) -> None:
    log("\n=== Conductor board-delete patch ===", quiet)
    cp = run(
        [
            "docker",
            "exec",
            "iotronic-conductor",
            "grep",
            "-c",
            "except exception:",
            "/usr/local/lib/python3.6/dist-packages/iotronic/conductor/endpoints.py",
        ],
        timeout=20,
    )
    count = (cp.stdout or "").strip()
    if count == "0":
        rep.add_ok("conductor except-exception patch present")
        return
    rep.add_fail(f"conductor still has 'except exception:' ({count})")
    if heal:
        # The fix is bind-mounted by docker-compose.yml; a recreate re-applies it.
        compose_up(["iotronic-conductor"], quiet)
        run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "--force-recreate", "iotronic-conductor"],
            timeout=300, cwd=ROOT)
        time.sleep(15)
        cp2 = run(["docker", "exec", "iotronic-conductor", "grep", "-c", "except exception:",
                   "/usr/local/lib/python3.6/dist-packages/iotronic/conductor/endpoints.py"], timeout=20)
        if (cp2.stdout or "").strip() == "0":
            rep.add_healed("re-applied conductor except patch (recreated container)")
            rep.fail = [f for f in rep.fail if "conductor still has" not in f]
            rep.add_ok("conductor except-exception patch present (healed)")


def print_summary(rep: Report) -> int:
    print("\n========== DEMO STATUS ==========")
    print(f"OK      : {len(rep.ok)}")
    print(f"HEALED  : {len(rep.healed)}")
    print(f"WARN    : {len(rep.warn)}")
    print(f"FAIL    : {len(rep.fail)}")
    if rep.healed:
        print("\nHealed:")
        for m in rep.healed:
            print(f"  + {m}")
    if rep.warn:
        print("\nWarnings:")
        for m in rep.warn:
            print(f"  ! {m}")
    if rep.fail:
        print("\nStill failing:")
        for m in rep.fail:
            print(f"  x {m}")
    ready = len(rep.fail) == 0
    print("\nRESULT  :", "READY" if ready else "NOT READY")
    print("=================================")
    return 0 if ready else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="Only report; do not restart/relaunch anything",
    )
    ap.add_argument(
        "--heal",
        action="store_true",
        help="Attempt to fix failures (default unless --check-only)",
    )
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument(
        "--skip-hello",
        action="store_true",
        help="Skip HelloName PluginCall smoke test",
    )
    args = ap.parse_args()
    heal = (args.heal or not args.check_only) and not args.check_only

    log(
        f"S4T demo verify (heal={'on' if heal else 'off'}) host={HOST}",
        args.quiet,
    )
    rep = Report()
    try:
        ensure_containers(rep, heal, args.quiet)
        ensure_http_endpoints(rep, heal, args.quiet)
        ensure_conductor_patch(rep, heal, args.quiet)
        ensure_boards(rep, heal, args.quiet)
        ensure_plugins(rep, heal, args.quiet)
        ensure_metrics(rep, heal, args.quiet)
        ensure_webservices(rep, heal, args.quiet)
        ensure_fl(rep, heal, args.quiet)
        if not args.skip_hello:
            ensure_hello_smoke(rep, heal, args.quiet)
    except Exception as exc:
        print(f"SCRIPT ERROR: {exc}", file=sys.stderr)
        return 2
    return print_summary(rep)


if __name__ == "__main__":
    sys.exit(main())
