#!/usr/bin/env python3
"""360-degree Fleet panel verification: 3 boards, HelloName plugin, fleet CRUD + ops."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOST = os.environ.get("S4T_LAB_HOST", (ROOT / "vm-ip.txt").read_text().strip())
HELLO_SRC = ROOT / "plugins/hello_name.py"
LR_USER = os.environ.get("S4T_LR_USER", "me")
LR_PASS = os.environ.get("S4T_LR_PASS", "arancino")
WAMP_URL = "wss://crossbar:8181"

VERIFY_BOARDS = [
    ("board-delta", "board-delta-lab2026", 1477, "lightning-rod-4"),
    ("board-epsilon", "board-epsilon-lab2026", 1478, "lightning-rod-5"),
    ("board-zeta", "board-zeta-lab2026", 1479, "lightning-rod-6"),
]
FLEET_FULL = "fleet-verify-hello-3"
FLEET_PAIR = "fleet-verify-pair"
PLUGIN_NAME = "HelloName"
CALL_NAME = "fleet-360-demo"

PASS = 0
FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  OK   {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL {msg}")


def keystone_token() -> str:
    body = json.dumps(
        {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": "admin",
                            "domain": {"name": "Default"},
                            "password": "s4t",
                        }
                    },
                },
                "scope": {
                    "project": {"name": "admin", "domain": {"name": "Default"}}
                },
            }
        }
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:5000/v3/auth/tokens",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.headers["X-Subject-Token"]


def api(token: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    headers = {"Content-Type": "application/json", "X-Auth-Token": token}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:8812{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def list_boards(token: str) -> list[dict]:
    _, body = api(token, "GET", "/v1/boards/")
    data = json.loads(body)
    return data.get("boards", data if isinstance(data, list) else [])


def wait_board_online(token: str, name: str, timeout: int = 90) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for b in list_boards(token):
            if b.get("name") == name and b.get("status") == "online":
                return b
        time.sleep(3)
    return None


def lr_operative(container: str) -> bool:
    try:
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                container,
                "python3",
                "-c",
                "import json; d=json.load(open('/etc/iotronic/settings.json')); "
                "b=d.get('iotronic',{}).get('board',{}); "
                "print(b.get('status',''), b.get('code',''))",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        ).strip()
        status, code = out.split(None, 1) if out else ("", "")
        return status == "operative" and code and code != "<REGISTRATION-TOKEN>"
    except Exception:
        return False


def configure_lr(port: int, container: str, code: str) -> bool:
    if lr_operative(container):
        print(f"    LR :{port} ({container}) already operative")
        return True
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("    WARN playwright missing — pip install playwright && playwright install chromium")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"http://{HOST}:{port}/login", wait_until="networkidle", timeout=60000)
        if page.locator('input[name="username"]').count():
            page.fill('input[name="username"]', LR_USER)
            page.fill('input[name="password"]', LR_PASS)
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            page.wait_for_timeout(1500)
        page.goto(f"http://{HOST}:{port}/config", wait_until="networkidle", timeout=60000)
        if page.locator("#urlwagent").count() == 0:
            browser.close()
            return lr_operative(container)
        page.fill("#urlwagent", WAMP_URL)
        page.fill("#code", code)
        page.locator('input[name="reg_btn"], input[value="CONFIGURE"]').first.click()
        page.wait_for_timeout(15000)
        browser.close()
    return lr_operative(container)


def ensure_hello_plugin(token: str) -> str:
    """Create/update HelloName via iotronic-ui container (pickle code)."""
    hello_path = HELLO_SRC
    if not hello_path.is_file():
        raise RuntimeError(f"Missing {hello_path}")
    subprocess.run(
        ["docker", "cp", str(hello_path), "iotronic-ui:/tmp/hello_name_plugin.py"],
        check=True,
        timeout=30,
    )
    script = r"""
import cPickle, json, urllib2
PLUGIN_PATH = '/tmp/hello_name_plugin.py'
NAME = 'HelloName'
body = json.dumps({'auth': {'identity': {'methods': ['password'], 'password': {'user': {'name': 'admin', 'domain': {'name': 'Default'}, 'password': 's4t'}}}, 'scope': {'project': {'name': 'admin', 'domain': {'name': 'Default'}}}}})
r = urllib2.urlopen(urllib2.Request('http://keystone:5000/v3/auth/tokens', body, {'Content-Type': 'application/json'}))
token = r.info().get('X-Subject-Token')
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint='http://iotronic-conductor:8812/v1/')
code = open(PLUGIN_PATH).read().decode('utf-8').encode('ascii', 'replace')
pickled = cPickle.dumps(str(code))
plugins = dict((p.name, p.uuid) for p in c.plugin.list(all_plugins=True))
if NAME in plugins:
    c.plugin.update(plugins[NAME], {'name': NAME, 'public': True, 'callable': True, 'code': pickled})
    print plugins[NAME]
else:
    p = c.plugin.create(name=NAME, public=True, callable=True, code=str(code), parameters={})
    print p.uuid
"""
    out = subprocess.check_output(
        ["docker", "exec", "iotronic-ui", "python2.7", "-c", script],
        text=True,
        timeout=60,
    ).strip()
    return out.splitlines()[-1]


def fleet_by_name(token: str, name: str) -> dict | None:
    _, body = api(token, "GET", "/v1/fleets/")
    data = json.loads(body)
    for f in data.get("fleets", []):
        if f.get("name") == name:
            return f
    return None


def ensure_fleet(token: str, name: str, desc: str) -> str:
    existing = fleet_by_name(token, name)
    if existing:
        return existing["uuid"]
    code, body = api(token, "POST", "/v1/fleets/", {"name": name, "description": desc})
    if code not in (200, 201):
        raise RuntimeError(f"fleet create {name}: HTTP {code} {body[:200]}")
    return json.loads(body)["uuid"]


def set_fleet_members(token: str, fleet_id: str, board_ids: list[str]) -> None:
    selected = set(board_ids)
    _, body = api(token, "GET", f"/v1/fleets/{fleet_id}/boards/")
    current = json.loads(body).get("boards", [])
    current_ids = {b["uuid"] for b in current}
    for bid in selected:
        if bid not in current_ids:
            code, resp = api(token, "PATCH", f"/v1/boards/{bid}", {"fleet": fleet_id})
            if code != 200:
                raise RuntimeError(f"assign {bid}: {code} {resp[:120]}")
    for b in current:
        if b["uuid"] not in selected:
            api(token, "PATCH", f"/v1/boards/{b['uuid']}", {"fleet": None})


def fleet_board_ids(token: str, fleet_id: str) -> list[str]:
    _, body = api(token, "GET", f"/v1/fleets/{fleet_id}/boards/")
    return [b["uuid"] for b in json.loads(body).get("boards", [])]


def plugin_inject(token: str, board_id: str, plugin_id: str) -> None:
    code, body = api(
        token, "PUT", f"/v1/boards/{board_id}/plugins/", {"plugin": plugin_id, "onboot": False}
    )
    if code not in (200, 201, 202):
        raise RuntimeError(f"inject {board_id}: HTTP {code} {body[:120]}")


def plugin_action(token: str, board_id: str, plugin_id: str, action: str, params: dict) -> str:
    code, body = api(
        token,
        "POST",
        f"/v1/boards/{board_id}/plugins/{plugin_id}",
        {"action": action, "parameters": params},
    )
    if code not in (200, 201, 202):
        raise RuntimeError(f"{action} {board_id}: HTTP {code} {body[:120]}")
    return body


def plugin_remove(token: str, board_id: str, plugin_id: str) -> None:
    code, body = api(token, "DELETE", f"/v1/boards/{board_id}/plugins/{plugin_id}")
    if code not in (200, 204):
        raise RuntimeError(f"remove {board_id}: HTTP {code} {body[:120]}")


def run_fleet_op(token: str, fleet_id: str, plugin_id: str, op: str, params: dict | None = None) -> int:
    params = params or {}
    ok_count = 0
    boards = fleet_board_ids(token, fleet_id)
    for bid in boards:
        try:
            if op == "inject":
                plugin_inject(token, bid, plugin_id)
            elif op == "call":
                plugin_action(token, bid, plugin_id, "PluginCall", params)
            elif op == "stop":
                plugin_action(token, bid, plugin_id, "PluginStop", {})
            elif op == "remove":
                plugin_remove(token, bid, plugin_id)
            ok_count += 1
        except Exception as exc:
            print(f"    op {op} failed on {bid[:8]}: {exc}")
    return ok_count


def horizon_smoke(fleet_id: str) -> None:
    cookie = "/tmp/fleet360-cookie.txt"
    Path(cookie).unlink(missing_ok=True)
    login_html = subprocess.check_output(
        ["curl", "-s", "-c", cookie, f"http://{HOST}/horizon/auth/login/"],
        text=True,
    )
    csrf_match = re.search(
        r"name=['\"]csrfmiddlewaretoken['\"]\s+value=['\"]([^'\"]+)['\"]",
        login_html,
    )
    if not csrf_match:
        bad("Horizon login page missing CSRF token")
        return
    csrf = csrf_match.group(1)
    subprocess.run(
        [
            "curl", "-sf", "-c", cookie, "-b", cookie, "-L",
            "-d", f"csrfmiddlewaretoken={csrf}&username=admin&password=s4t",
            "-e", f"http://{HOST}/horizon/auth/login/",
            f"http://{HOST}/horizon/auth/login/?next=/horizon/iot/fleets/",
        ],
        check=False,
        capture_output=True,
    )
    paths = [
        ("/horizon/iot/fleets/", "Fleets"),
        (f"/horizon/iot/fleets/{fleet_id}/detail/", "Fleet detail"),
    ]
    for path, label in paths:
        body = subprocess.check_output(
            ["curl", "-s", "-L", "-b", cookie, f"http://{HOST}{path}"],
            text=True,
        )
        code = subprocess.check_output(
            [
                "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "-L", "-b", cookie, f"http://{HOST}{path}",
            ],
            text=True,
        ).strip()
        if code != "200":
            bad(f"Horizon GET {path} HTTP {code}")
            continue
        if "Login - OpenStack Dashboard" in body:
            bad(f"Horizon {label} returned login page (session auth failed)")
        elif label == "Fleets" and "Fleets" not in body:
            bad(f"Horizon {label} page missing expected content")
        else:
            ok(f"Horizon GET {path} HTTP 200")


def lr_log_proxy_smoke(board_names: list[str]) -> None:
    try:
        health = subprocess.check_output(
            ["curl", "-sf", "http://127.0.0.1:8092/health"],
            text=True,
            timeout=5,
        )
        if json.loads(health).get("ok"):
            ok("lr-log-proxy /health")
        else:
            bad(f"lr-log-proxy /health unexpected: {health[:80]}")
    except Exception as exc:
        bad(f"lr-log-proxy unreachable ({exc})")
        return

    try:
        raw = subprocess.check_output(
            ["curl", "-sf", "http://127.0.0.1:8092/api/lr-map?refresh=1"],
            text=True,
            timeout=15,
        )
        data = json.loads(raw)
        mapped = data.get("by_name") or {}
        if len(mapped) >= len(board_names):
            ok(f"lr-log-proxy maps {len(mapped)} LR containers")
        else:
            bad(f"lr-log-proxy maps {len(mapped)}/{len(board_names)} boards")
        for name in board_names:
            qs = f"boards={name}&tail=3&refresh=1"
            log_raw = subprocess.check_output(
                ["curl", "-sf", f"http://127.0.0.1:8092/api/lr-logs?{qs}"],
                text=True,
                timeout=15,
            )
            entry = json.loads(log_raw).get("boards", {}).get(name, {})
            if entry.get("container"):
                ok(f"lr-logs {name} -> {entry['container']}")
            else:
                bad(f"lr-logs {name} has no container mapping")
    except Exception as exc:
        bad(f"lr-log-proxy map/logs ({exc})")


def boards_panel_smoke() -> None:
    try:
        out = subprocess.check_output(
            [
                "docker", "exec", "iotronic-ui", "bash", "-c",
                "cd /usr/share/openstack-dashboard && python2.7 manage.py shell -c "
                "\"from iotronic_ui.iot.boards import tabs; "
                "print ','.join(t.slug for t in tabs.BoardDetailTabs.tabs)\"",
            ],
            text=True,
            timeout=30,
        ).strip()
        if "logs" in out.split(","):
            ok(f"Boards detail tabs: {out}")
        else:
            bad(f"Boards detail tabs missing LR logs: {out}")
    except Exception as exc:
        bad(f"boards patch import: {exc}")

    try:
        out = subprocess.check_output(
            [
                "docker", "exec", "iotronic-ui", "python2", "-c",
                "from iotronic_ui_lab.iot.lr_logs import helpers as h; "
                "p=h.board_log_panel('board-alpha','',tail=3); "
                "print p.get('container') or 'none'",
            ],
            text=True,
            timeout=20,
        ).strip()
        if out and out != "none":
            ok(f"Boards LR log helper -> {out}")
        else:
            bad("Boards LR log helper returned no container")
    except Exception as exc:
        bad(f"boards LR log helper: {exc}")


def main() -> int:
    print("=== Fleet 360 verification ===")
    print(f"Host: {HOST}")

    print("\n[1] LR instances for delta/epsilon/zeta (1477-1479)")
    for _, _, port, container in VERIFY_BOARDS:
        try:
            c = subprocess.check_output(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://127.0.0.1:{port}/"],
                text=True,
                timeout=5,
            ).strip()
            if c in ("200", "302"):
                ok(f"LR UI :{port} HTTP {c}")
            else:
                bad(f"LR UI :{port} HTTP {c}")
        except Exception as exc:
            bad(f"LR UI :{port} unreachable ({exc})")

    token = keystone_token()
    board_map = {b["name"]: b for b in list_boards(token)}

    print("\n[2] Onboard board-delta, board-epsilon, board-zeta")
    for name, code, port, container in VERIFY_BOARDS:
        if name not in board_map:
            bad(f"Board {name} missing in conductor")
            continue
        if board_map[name].get("status") == "online":
            ok(f"{name} already online")
            continue
        if configure_lr(port, container, code):
            ok(f"{name} LR :{port} configured")
        else:
            bad(f"{name} LR configure failed")

    print("\n[3] Wait for boards online")
    online_ids = []
    for name, _, _, _ in VERIFY_BOARDS:
        b = wait_board_online(token, name, timeout=120)
        if b:
            online_ids.append(b["uuid"])
            ok(f"{name} online uuid={b['uuid'][:8]}...")
        else:
            bad(f"{name} not online after wait")

    if len(online_ids) < 3:
        print("\nAborting fleet ops — need 3 online boards")
        print(f"\n=== Results: {PASS} OK | {FAIL} FAIL ===")
        return 1

    print("\n[4] Ensure HelloName demo plugin")
    try:
        plugin_id = ensure_hello_plugin(token)
        ok(f"HelloName plugin uuid={plugin_id[:8]}...")
    except Exception as exc:
        bad(f"HelloName plugin: {exc}")
        print(f"\n=== Results: {PASS} OK | {FAIL} FAIL ===")
        return 1

    print("\n[5] Create fleet-verify-hello-3 (3 members)")
    try:
        fleet3 = ensure_fleet(token, FLEET_FULL, "360 verify - HelloName on delta/epsilon/zeta")
        set_fleet_members(token, fleet3, online_ids)
        members = fleet_board_ids(token, fleet3)
        if len(members) == 3:
            ok(f"{FLEET_FULL} has 3 members")
        else:
            bad(f"{FLEET_FULL} member count {len(members)} != 3")
    except Exception as exc:
        bad(f"fleet 3-member: {exc}")
        fleet3 = None

    print("\n[6] Fleet inject HelloName on all members")
    if fleet3:
        n = run_fleet_op(token, fleet3, plugin_id, "inject")
        if n == 3:
            ok(f"Inject on {n}/3 boards")
        else:
            bad(f"Inject on {n}/3 boards")

    print("\n[7] Fleet PluginCall HelloName")
    if fleet3:
        n = run_fleet_op(token, fleet3, plugin_id, "call", {"name": CALL_NAME})
        if n == 3:
            ok(f"PluginCall on {n}/3 boards (name={CALL_NAME})")
        else:
            bad(f"PluginCall on {n}/3 boards")

    print("\n[8] Fleet remove HelloName on 3-member fleet")
    if fleet3:
        n_rm = run_fleet_op(token, fleet3, plugin_id, "remove")
        if n_rm == 3:
            ok(f"Remove plugin on {n_rm}/3 boards")
        else:
            bad(f"Remove on {n_rm}/3 boards")

    print("\n[9] Create fleet-verify-pair (2 members) — board moves between fleets")
    try:
        fleet2 = ensure_fleet(token, FLEET_PAIR, "360 verify - pair subset")
        set_fleet_members(token, fleet2, online_ids[:2])
        if len(fleet_board_ids(token, fleet2)) == 2:
            ok(f"{FLEET_PAIR} has 2 members (delta+epsilon)")
        else:
            bad(f"{FLEET_PAIR} wrong member count")
        if len(fleet_board_ids(token, fleet3)) == 1:
            ok(f"{FLEET_FULL} retains zeta only after pair assignment")
        else:
            bad(f"{FLEET_FULL} unexpected members after pair split")
        n = run_fleet_op(token, fleet2, plugin_id, "inject")
        if n == 2:
            ok(f"Inject on pair fleet {n}/2")
        else:
            bad(f"Inject on pair fleet {n}/2")
        n_call = run_fleet_op(token, fleet2, plugin_id, "call", {"name": CALL_NAME})
        if n_call == 2:
            ok(f"PluginCall on pair fleet {n_call}/2")
        else:
            bad(f"PluginCall on pair fleet {n_call}/2")
        n_rm2 = run_fleet_op(token, fleet2, plugin_id, "remove")
        if n_rm2 == 2:
            ok(f"Remove plugin on pair fleet {n_rm2}/2")
        else:
            bad(f"Remove on pair fleet {n_rm2}/2")
    except Exception as exc:
        bad(f"pair fleet: {exc}")
        fleet2 = None

    print("\n[10] Horizon UI smoke")
    if fleet3:
        horizon_smoke(fleet3)

    print("\n[11] Fleet helpers import (lab patch)")
    try:
        out = subprocess.check_output(
            [
                "docker", "exec", "iotronic-ui", "bash", "-c",
                "cd /usr/share/openstack-dashboard && python2.7 manage.py shell -c "
                "\"from iotronic_ui.iot.fleets import fleet_helpers, tables; "
                "print len(tables.FleetsTable._meta.row_actions)\"",
            ],
            text=True,
            timeout=30,
        ).strip()
        if int(out) >= 8:
            ok(f"Fleets table row actions: {out}")
        else:
            bad(f"Fleets table row actions: {out}")
    except Exception as exc:
        bad(f"fleet patch import: {exc}")

    print("\n[12] LR log proxy (Boards + Fleets logs)")
    lr_names = sorted({b[0] for b in VERIFY_BOARDS} | {"board-alpha", "board-beta", "board-gamma"})
    lr_log_proxy_smoke(lr_names)

    print("\n[13] Boards panel LR logs tab")
    boards_panel_smoke()

    print("\n[14] Core lab services")
    for svc in ("lr-log-proxy", "fl-control", "iotronic-ui", "iotronic-conductor"):
        st = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Status}}", svc],
            text=True,
        ).strip()
        if st == "running":
            ok(f"docker {svc} running")
        else:
            bad(f"docker {svc} status={st}")
    try:
        subprocess.check_call(
            ["curl", "-sf", "http://127.0.0.1:8091/health"],
            stdout=subprocess.DEVNULL,
            timeout=5,
        )
        ok("fl-control /health")
    except Exception as exc:
        bad(f"fl-control health ({exc})")

    print(f"\n=== Results: {PASS} OK | {FAIL} FAIL ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
