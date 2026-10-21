#!/usr/bin/env python3
"""WSTUN demo — idempotent setup with port validation (local 50000 → cloud 5000x)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:  # optional: only needed to capture Horizon screenshots for slides
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ROOT = Path(__file__).resolve().parent.parent.parent
HOST = os.environ.get("S4T_LAB_HOST", (ROOT / "vm-ip.txt").read_text().strip())
BOARD_NAME = os.environ.get("S4T_BOARD", "board-alpha")
SERVICE_NAME = os.environ.get("S4T_SERVICE", "lr-nginx-demo")
LOCAL_PORT = int(os.environ.get("S4T_WS_LOCAL_PORT", "50000"))
HZ_USER = os.environ.get("S4T_HORIZON_USER", "admin")
HZ_PASS = os.environ.get("S4T_HORIZON_PASS", "s4t")
STATE_FILE = Path(__file__).resolve().parent / "wstun-state.json"
ASSETS = ROOT / "docs" / "screenshots"


def keystone_token() -> str:
    body = json.dumps({
        "auth": {
            "identity": {"methods": ["password"], "password": {"user": {
                "name": "admin", "domain": {"name": "Default"}, "password": "s4t",
            }}},
            "scope": {"project": {"name": "admin", "domain": {"name": "Default"}}},
        }
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:5000/v3/auth/tokens", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.headers["X-Subject-Token"]


def api(token: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    headers = {"Content-Type": "application/json", "X-Auth-Token": token}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:8812{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def board_uuid(token: str, name: str) -> str:
    _, body = api(token, "GET", "/v1/boards/")
    boards = json.loads(body)
    if isinstance(boards, dict):
        boards = boards.get("boards", [])
    for b in boards:
        if b.get("name") == name:
            return b["uuid"]
    raise RuntimeError(f"Board {name} not found")


def list_services(token: str) -> list[dict]:
    _, body = api(token, "GET", "/v1/services/")
    return json.loads(body).get("services", [])


def delete_service(token: str, uuid: str) -> None:
    code, body = api(token, "DELETE", f"/v1/services/{uuid}")
    print(f"DELETE service {uuid} HTTP {code}: {body[:120]}")


def ensure_service(token: str) -> str:
    for s in list_services(token):
        if s.get("name") == SERVICE_NAME:
            port = int(s.get("port") or 0)
            if port != LOCAL_PORT:
                print(f"WARN service {SERVICE_NAME} has port={port}, expected {LOCAL_PORT} — recreating")
                delete_service(token, s["uuid"])
                time.sleep(1)
                break
            print(f"OK service {SERVICE_NAME} port={port} uuid={s['uuid']}")
            return s["uuid"]
    code, body = api(token, "POST", "/v1/services", {
        "name": SERVICE_NAME, "port": LOCAL_PORT, "protocol": "TCP",
    })
    if code not in (200, 201):
        raise RuntimeError(f"Create service failed HTTP {code}: {body}")
    svc = json.loads(body)
    port = int(svc.get("port") or 0)
    if port < 1:
        raise RuntimeError(f"Service created with invalid port {port}")
    print(f"CREATED service uuid={svc['uuid']} port={port}")
    return svc["uuid"]


def disable_on_board(token: str, board_id: str) -> None:
    path = f"/v1/boards/{board_id}/services/{SERVICE_NAME}/action"
    api(token, "POST", path, {"action": "ServiceDisable"})


def enable_on_board(token: str, board_id: str) -> int:
    path = f"/v1/boards/{board_id}/services/{SERVICE_NAME}/action"
    code, body = api(token, "POST", path, {"action": "ServiceEnable"})
    print(f"ServiceEnable HTTP {code}: {body[:200]}")
    if code not in (200, 201) and "AlreadyExposed" not in body:
        raise RuntimeError(f"ServiceEnable failed: {body}")
    time.sleep(4)
    _, exposed = api(token, "GET", f"/v1/boards/{board_id}/services/")
    for item in json.loads(exposed).get("exposed", []):
        pub = int(item.get("public_port") or 0)
        if pub >= 50001:
            return pub
    raise RuntimeError(f"No public_port in exposed list: {exposed}")


def curl_code(url: str) -> str:
    try:
        return subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "8", url],
            text=True,
        ).strip()
    except Exception:
        return "000"


def _fill_port_field(page, port: int) -> None:
    for locator in (
        page.get_by_label("Porta"),
        page.get_by_label("Port"),
        page.locator('input[name*="port" i], input[id*="port" i]'),
        page.locator('input[type="number"]').nth(0),
    ):
        try:
            if locator.count() and locator.first.is_visible(timeout=2000):
                locator.first.fill(str(port))
                return
        except Exception:
            continue
    raise RuntimeError("Port field not found on Create Service form")


def capture_ui(board_id: str) -> None:
    if sync_playwright is None or os.environ.get("S4T_CAPTURE", "0") != "1":
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page(viewport={"width": 1400, "height": 900})
        page.goto(f"http://{HOST}/horizon/auth/login/", wait_until="networkidle", timeout=90000)
        page.fill('input[name="username"], #id_username', HZ_USER)
        page.fill('input[name="password"], #id_password', HZ_PASS)
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.wait_for_timeout(4000)

        try:
            page.goto(f"http://{HOST}/horizon/iot/services/create/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(800)
            for name_loc in (
                page.get_by_label("Service Name"),
                page.get_by_label("Nome servizio"),
                page.locator('input[name*="name" i]').first,
            ):
                try:
                    if name_loc.count() and name_loc.first.is_visible(timeout=2000):
                        name_loc.first.fill(SERVICE_NAME)
                        break
                except Exception:
                    continue
            _fill_port_field(page, LOCAL_PORT)
            page.screenshot(path=str(ASSETS / "horizon-service-create-filled.png"), full_page=True)
            print("CAPTURE horizon-service-create-filled.png (port=50000)")
        except Exception as exc:
            print(f"WARN create-form screenshot skipped: {exc}")

        for url, rel in [
            ("/horizon/iot/services/", "horizon-services-list.png"),
            ("/horizon/iot/", "horizon-boards-with-services.png"),
            ("/horizon/iot/webservices/", "horizon-webservices-dashboard.png"),
        ]:
            page.goto(f"http://{HOST}{url}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(ASSETS / rel), full_page=True)
            print(f"CAPTURE {rel}")


def main() -> int:
    if LOCAL_PORT < 1 or LOCAL_PORT > 65535:
        print(f"FAIL invalid LOCAL_PORT={LOCAL_PORT}")
        return 1
    print(f"=== WSTUN setup {HOST} board={BOARD_NAME} local={LOCAL_PORT} ===")
    token = keystone_token()
    board_id = board_uuid(token, BOARD_NAME)
    ensure_service(token)
    cloud_port = enable_on_board(token, board_id)
    url = f"http://{HOST}:{cloud_port}/"
    code = curl_code(url)
    ok = code == "200"
    print(f"{'OK' if ok else 'FAIL'} {url} → HTTP {code}")
    STATE_FILE.write_text(json.dumps({
        "host": HOST, "board": BOARD_NAME, "board_uuid": board_id,
        "service": SERVICE_NAME, "local_port": LOCAL_PORT,
        "cloud_port": cloud_port, "verified": ok,
    }, indent=2))
    try:
        capture_ui(board_id)
    except Exception as exc:
        print(f"WARN UI capture failed (API demo OK): {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
