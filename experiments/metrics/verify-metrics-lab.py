#!/usr/bin/env python3
"""E2E verification for S4T metrics stack (gateway, InfluxDB, Grafana, Horizon proxy)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parent.parent.parent
HOST = os.environ.get("S4T_LAB_HOST", (ROOT / "vm-ip.txt").read_text().strip())

METRICS = os.environ.get("METRICS_SERVER", f"http://127.0.0.1:8093")
GRAFANA = os.environ.get("GRAFANA_URL", f"http://{HOST}:3000")
HORIZON = os.environ.get("HORIZON_URL", f"http://{HOST}")

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


def http_get(url: str, timeout: int = 10) -> tuple[int, str]:
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, str(exc)


def http_json(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": exc.reason}
        return exc.code, payload
    except Exception as exc:
        return 0, {"error": str(exc)}


def docker_running(name: str) -> bool:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return name in out.decode("utf-8", "replace").splitlines()
    except Exception:
        return False


def main() -> int:
    print(f"=== S4T Metrics lab verification (host={HOST}) ===\n")

    print("[1] Containers")
    for c in ("influxdb", "metrics-gateway", "grafana"):
        if docker_running(c):
            ok(f"container {c} running")
        else:
            bad(f"container {c} not running")

    print("\n[2] metrics-gateway /health")
    code, body = http_get(f"{METRICS.rstrip('/')}/health")
    health_ok = False
    if code == 200:
        try:
            health_ok = bool(json.loads(body).get("ok"))
        except Exception:
            health_ok = '"ok":true' in body.replace(" ", "")
    if health_ok:
        ok("metrics-gateway healthy + Influx reachable")
    else:
        bad(f"metrics-gateway health failed ({code}): {body[:120]}")

    print("\n[3] Provision test stream")
    prov_body = {
        "board_uuid": str(uuid.uuid4()),
        "board_name": "verify-board",
        "plugin_uuid": str(uuid.uuid4()),
        "plugin_name": "verify-plugin",
        "measurement": "environmental_data",
        "field_schema": ["Temperature", "Humidity"],
    }
    code, prov = http_json("POST", f"{METRICS.rstrip('/')}/v1/streams/provision", prov_body)
    token = prov.get("metrics_token") or prov.get("write_token")
    if code == 200 and token:
        ok(f"stream provisioned token={token[:8]}...")
    else:
        bad(f"provision failed ({code}): {prov}")
        print(f"\nResult: {PASS} OK | {FAIL} FAIL")
        return 1

    print("\n[4] Write test point")
    write_body = {"fields": {"Temperature": 21.0, "Humidity": 50.0}, "tags": {"sensor": "verify"}}
    write_url = prov.get("metrics_url") or f"{METRICS.rstrip('/')}/v1/metrics/write"
    if "metrics-gateway" in write_url:
        write_url = f"{METRICS.rstrip('/')}/v1/metrics/write"
    req = request.Request(
        write_url,
        data=json.dumps(write_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                ok("write accepted by gateway")
            else:
                bad(f"write unexpected status {resp.status}")
    except Exception as exc:
        bad(f"write failed: {exc}")

    print("\n[5] InfluxDB COUNT query")
    try:
        out = subprocess.check_output(
            [
                "docker", "exec", "influxdb", "influx",
                "-username", "admin", "-password", "admin",
                "-execute", "SELECT COUNT(*) FROM environmental_data",
                "-database", "s4t_iot",
            ],
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        text = out.decode("utf-8", "replace")
        if any(ch.isdigit() for ch in text):
            ok("environmental_data has points in s4t_iot")
        else:
            bad(f"no count in influx output: {text[:120]}")
    except Exception as exc:
        bad(f"influx query failed: {exc}")

    print("\n[6] Grafana")
    code, _ = http_get(f"{GRAFANA.rstrip('/')}/api/health")
    if code == 200:
        ok("Grafana /api/health OK")
    else:
        bad(f"Grafana health failed ({code})")

    print("\n[7] Horizon metrics proxy (optional)")
    code, body = http_get(f"{HORIZON.rstrip('/')}/horizon/metrics-live/api/health")
    if code == 200:
        ok("Horizon /horizon/metrics-live/ proxy OK")
    else:
        bad(f"Horizon metrics proxy unreachable ({code}) — recreate iotronic-ui if needed")

    print(f"\nResult: {PASS} OK | {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
