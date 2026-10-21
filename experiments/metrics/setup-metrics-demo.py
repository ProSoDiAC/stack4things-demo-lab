#!/usr/bin/env python3
"""Reset the metrics demo data, deploy the EnvironmentalDemo plugin, provision a stream and start it with cloud metrics."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOST = os.environ.get("S4T_LAB_HOST", (ROOT / "vm-ip.txt").read_text().strip())
PLUGIN_PATH = ROOT / "plugins" / "environmental_demo.py"
PLUGIN_NAME = os.environ.get("CH15_PLUGIN_NAME", "EnvironmentalDemo")
BOARD_NAME = os.environ.get("CH15_BOARD_NAME", "board-alpha")
METRICS = os.environ.get("METRICS_SERVER", f"http://127.0.0.1:8093")
MEASUREMENT = "environmental_data"
SDK_PATH = ROOT / "experiments" / "metrics" / "s4t_metrics.py"
LR_BY_BOARD = {
    "board-alpha": "lightning-rod",
    "board-beta": "lightning-rod-2",
    "board-gamma": "lightning-rod-3",
    "board-delta": "lightning-rod-4",
    "board-epsilon": "lightning-rod-5",
    "board-zeta": "lightning-rod-6",
}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)


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
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def clean_lab_data() -> None:
    print("\n[1] Clean InfluxDB + metrics registry")
    subprocess.run(
        [
            "docker", "exec", "influxdb", "influx",
            "-username", "admin", "-password", "admin",
            "-execute", "DROP DATABASE s4t_iot",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    run(
        [
            "docker", "exec", "influxdb", "influx",
            "-username", "admin", "-password", "admin",
            "-execute", "CREATE DATABASE s4t_iot",
        ]
    )
    run(
        [
            "docker", "exec", "metrics-gateway", "sh", "-c",
            'echo \'{"streams": []}\' > /data/metrics_streams.json',
        ]
    )
    print("  cleaned s4t_iot and stream registry")


def ensure_plugin_uuid() -> str:
    print("\n[2] Create/update cloud plugin from plugins/environmental_demo.py")
    if not PLUGIN_PATH.is_file():
        raise SystemExit(f"Missing plugin source: {PLUGIN_PATH}")

    run(["docker", "cp", str(PLUGIN_PATH), "iotronic-ui:/tmp/environmental_demo_lab.py"])
    script = r"""
import cPickle, json, urllib2
PLUGIN_PATH = '/tmp/environmental_demo_lab.py'
NAME = '%s'
body = json.dumps({'auth': {'identity': {'methods': ['password'], 'password': {'user': {'name': 'admin', 'domain': {'name': 'Default'}, 'password': 's4t'}}}, 'scope': {'project': {'name': 'admin', 'domain': {'name': 'Default'}}}}})
r = urllib2.urlopen(urllib2.Request('http://keystone:5000/v3/auth/tokens', body, {'Content-Type': 'application/json'}))
token = r.info().get('X-Subject-Token')
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint='http://iotronic-conductor:8812/v1/')
code = open(PLUGIN_PATH).read().decode('utf-8').encode('ascii', 'replace')
pickled = cPickle.dumps(str(code))
plugins = dict((p.name, p.uuid) for p in c.plugin.list(all_plugins=True))
if NAME in plugins:
    c.plugin.update(plugins[NAME], {'name': NAME, 'public': True, 'callable': False, 'code': pickled, 'parameters': {}})
    print plugins[NAME]
else:
    p = c.plugin.create(name=NAME, public=True, callable=False, code=str(code), parameters={})
    print p.uuid
""" % PLUGIN_NAME.replace("'", "\\'")

    out = subprocess.check_output(
        ["docker", "exec", "iotronic-ui", "python2.7", "-c", script],
        text=True,
        timeout=120,
    ).strip()
    plugin_id = out.splitlines()[-1].strip()
    print(f"  plugin {PLUGIN_NAME} uuid={plugin_id}")
    return plugin_id


def find_board(token: str, name: str) -> dict:
    _, body = api(token, "GET", "/v1/boards/")
    boards = json.loads(body).get("boards", [])
    for board in boards:
        if board.get("name") == name:
            return board
    online = [b for b in boards if b.get("status") == "online"]
    if online:
        print(f"  WARN board {name} not found, using {online[0]['name']}")
        return online[0]
    raise RuntimeError(f"No online board found (wanted {name})")


def provision_metrics(board: dict, plugin_id: str) -> dict:
    print("\n[3] Provision metrics stream")
    payload = {
        "board_uuid": board["uuid"],
        "board_name": board["name"],
        "plugin_uuid": plugin_id,
        "plugin_name": PLUGIN_NAME,
        "measurement": MEASUREMENT,
        "field_schema": [
            "Temperature", "Humidity", "PM10", "PM25", "Wind_speed", "Pressure",
        ],
    }
    result = http_json("POST", f"{METRICS.rstrip('/')}/v1/streams/provision", payload)
    print(f"  stream={result.get('stream_id')} board={board['name']}")
    return result


def install_sdk_on_lr(board_name: str) -> None:
    container = LR_BY_BOARD.get(board_name, "lightning-rod")
    run(
        [
            "docker", "exec", container, "sh", "-c",
            "pip3 install -q pandas requests 2>/dev/null || pip install -q pandas requests",
        ]
    )
    run(
        [
            "docker", "exec", container, "python3", "-c",
            "import sys; sys.path.insert(0,'/opt/lab'); from s4t_metrics import MetricsWriter; print('sdk ok')",
        ]
    )
    print(f"  SDK ready on {container}")


def inject_and_start(token: str, board: dict, plugin_id: str, metrics: dict) -> None:
    print("\n[4] Install SDK + inject + Start on board")
    install_sdk_on_lr(board["name"])
    code, body = api(
        token,
        "PUT",
        f"/v1/boards/{board['uuid']}/plugins/",
        {"plugin": plugin_id, "onboot": True},
    )
    if code not in (200, 201, 202):
        raise RuntimeError(f"inject failed HTTP {code}: {body[:200]}")

    params = {
        "metrics_url": metrics.get("metrics_url"),
        "metrics_token": metrics.get("metrics_token"),
        "metrics_stream": metrics.get("metrics_stream"),
    }
    code, body = api(
        token,
        "POST",
        f"/v1/boards/{board['uuid']}/plugins/{plugin_id}",
        {"action": "PluginStart", "parameters": params},
    )
    if code not in (200, 201, 202):
        raise RuntimeError(f"start failed HTTP {code}: {body[:200]}")
    print(f"  started on {board['name']} with cloud metrics")


def wait_for_points(min_count: int = 1, timeout: int = 120) -> int:
    print("\n[5] Wait for InfluxDB points")
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = subprocess.check_output(
            [
                "docker", "exec", "influxdb", "influx",
                "-username", "admin", "-password", "admin",
                "-execute", f"SELECT COUNT(*) FROM {MEASUREMENT}",
                "-database", "s4t_iot",
            ],
            text=True,
        )
        digits = [int(x) for x in out.replace(",", " ").split() if x.isdigit()]
        count = max(digits) if digits else 0
        if count >= min_count:
            print(f"  {count} point(s) in {MEASUREMENT}")
            return count
        time.sleep(10)
    raise RuntimeError("No points written within timeout (check LR logs / CSV download)")


def main() -> int:
    print(f"=== Metrics demo setup (host={HOST}, board={BOARD_NAME}) ===")
    clean_lab_data()
    plugin_id = ensure_plugin_uuid()
    token = keystone_token()
    board = find_board(token, BOARD_NAME)
    if board.get("status") != "online":
        raise RuntimeError(f"Board {board.get('name')} is not online")
    metrics = provision_metrics(board, plugin_id)
    inject_and_start(token, board, plugin_id, metrics)
    count = wait_for_points()
    print(f"\nDone: {PLUGIN_NAME} running on {board['name']}, {count} point(s) in InfluxDB.")
    print(f"Grafana filter: board={board['name']}, measurement={MEASUREMENT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
