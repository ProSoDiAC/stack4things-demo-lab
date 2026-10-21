#!/usr/bin/env python3
"""Start/stop Flower FL server + live dashboard as background processes."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CH19 = ROOT / "vendor" / "ch19"
FL_EXP = Path(__file__).resolve().parent
RUN_DIR = FL_EXP / ".run"
PID_FILE = RUN_DIR / "fl-server.pids.json"
LOG_DIR = RUN_DIR / "logs"

DEFAULTS = {
    "fl_rounds": "2",
    "fl_port": "8087",
    "fl_host": "0.0.0.0",
    "fl_dashboard_port": "8090",
    "fl_dashboard_host": "0.0.0.0",
}


def _python() -> str:
    env_py = os.environ.get("FL_PYTHON")
    if env_py:
        return env_py
    candidates = [
        sys.executable,
        str(ROOT / ".venv" / "bin" / "python3"),
        "python3",
    ]
    for py in candidates:
        if not py:
            continue
        try:
            subprocess.run(
                [py, "-c", "import flwr"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return py
        except (OSError, subprocess.CalledProcessError):
            continue
    return sys.executable


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except OSError:
        return False


def _load_pids() -> dict:
    if not PID_FILE.is_file():
        return {}
    try:
        return json.loads(PID_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pids(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(data, indent=2))


def _alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate(pid: int, grace: float = 3.0) -> None:
    if not pid or not _alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + grace
    while time.time() < deadline and _alive(pid):
        time.sleep(0.2)
    if _alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def status(cfg: dict | None = None) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    port = int(cfg["fl_port"])
    dash_port = int(cfg["fl_dashboard_port"])
    pids = _load_pids()
    server_pid = int(pids.get("server", 0) or 0)
    dash_pid = int(pids.get("dashboard", 0) or 0)
    server_up = _alive(server_pid) or _port_open("127.0.0.1", port)
    dash_up = _alive(dash_pid) or _port_open("127.0.0.1", dash_port)
    return {
        "running": server_up,
        "dashboard_running": dash_up,
        "server_pid": server_pid if _alive(server_pid) else None,
        "dashboard_pid": dash_pid if _alive(dash_pid) else None,
        "fl_port": port,
        "fl_dashboard_port": dash_port,
        "fl_rounds": cfg.get("fl_rounds", DEFAULTS["fl_rounds"]),
    }


def stop(cfg: dict | None = None) -> dict:
    cfg = {**DEFAULTS, **_lab_file_cfg(), **(cfg or {})}
    pids = _load_pids()
    _terminate(int(pids.get("dashboard", 0) or 0))
    _terminate(int(pids.get("server", 0) or 0))
    _ensure_ports_free(cfg)
    if PID_FILE.is_file():
        PID_FILE.unlink()
    _clear_dashboard_state()
    return status(cfg)


def _pids_on_port(port: int) -> list[int]:
    found: list[int] = []
    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return found
    token = ":{0}".format(port)
    for line in out.splitlines():
        if token not in line:
            continue
        for part in line.split():
            if "pid=" not in part:
                continue
            raw = part.split("pid=", 1)[1].split(",", 1)[0]
            try:
                found.append(int(raw))
            except ValueError:
                continue
    return found


def _wait_port_free(host: str, port: int, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_open(host, int(port)):
            return
        time.sleep(0.2)
    _kill_port(int(port))
    time.sleep(0.3)


def _server_log_tail(n: int = 30) -> str:
    log_path = LOG_DIR / "flower-server.log"
    if not log_path.is_file():
        return ""
    try:
        lines = log_path.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def _kill_port(port: int) -> None:
    for pid in _pids_on_port(port):
        _terminate(pid)


def _ensure_ports_free(cfg: dict) -> None:
    for port in (int(cfg["fl_port"]), int(cfg["fl_dashboard_port"])):
        _kill_port(port)
        _wait_port_free("127.0.0.1", port)


def _clear_dashboard_state() -> None:
    state_path = Path("/tmp/fl_dashboard_state.json")
    if state_path.is_file():
        try:
            state_path.unlink()
        except OSError:
            pass


def _reset_dashboard_state(port: int, total_rounds: int, scenario: str = "heart") -> None:
    try:
        import urllib.error
        import urllib.request

        payload = json.dumps({
            "total_rounds": int(total_rounds),
            "fl_scenario": scenario,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:{0}/api/reset".format(port),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def _lab_file_cfg() -> dict:
    path = RUN_DIR / "lab_config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        mapped = {
            "fl_rounds": data.get("fl_rounds"),
            "fl_scenario": data.get("fl_scenario"),
            "fl_port": data.get("server_port"),
            "fl_dashboard_port": data.get("dashboard_port"),
        }
        return {k: v for k, v in mapped.items() if v}
    except (json.JSONDecodeError, OSError):
        return {}


def start(cfg: dict | None = None) -> dict:
    cfg = {**DEFAULTS, **_lab_file_cfg(), **(cfg or {})}
    stop(cfg)
    _ensure_ports_free(cfg)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    py = _python()
    scenario = str(cfg.get("fl_scenario", "heart"))
    test_csv = {
        "heart": "data_test_heart.csv",
        "pm": "data_test_pm.csv",
    }.get(scenario, "data_test_heart.csv")
    env = os.environ.copy()
    env.update(
        {
            "FL_ROUNDS": str(cfg["fl_rounds"]),
            "FL_PORT": str(cfg["fl_port"]),
            "FL_HOST": str(cfg["fl_host"]),
            "FL_SCENARIO": scenario,
            "FL_TEST_CSV": test_csv,
            "FL_DASHBOARD": "1",
            "FL_DASHBOARD_PORT": str(cfg["fl_dashboard_port"]),
            "FL_DASHBOARD_HOST": str(cfg["fl_dashboard_host"]),
            "PYTHONPATH": f"{FL_EXP}:{env.get('PYTHONPATH', '')}",
        }
    )

    dash_log = open(LOG_DIR / "dashboard.log", "a")
    dash_proc = subprocess.Popen(
        [py, str(FL_EXP / "dashboard" / "app.py")],
        cwd=str(FL_EXP),
        env=env,
        stdout=dash_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1)

    server_log = open(LOG_DIR / "flower-server.log", "a")
    server_proc = subprocess.Popen(
        [py, str(CH19 / "server.py")],
        cwd=str(CH19),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    _save_pids({"server": server_proc.pid, "dashboard": dash_proc.pid})

    dash_port = int(cfg["fl_dashboard_port"])
    fl_port = int(cfg["fl_port"])
    total_rounds = int(cfg["fl_rounds"])
    for _ in range(10):
        if _port_open("127.0.0.1", dash_port):
            _reset_dashboard_state(dash_port, total_rounds, scenario)
            break
        time.sleep(0.25)

    _wait_flower_grpc_ready(fl_port, server_proc.pid, timeout=45)

    st = status(cfg)
    if not st["running"]:
        raise RuntimeError("Flower server failed to start — check .run/logs/")
    tail = _server_log_tail()
    if "already in use" in tail:
        raise RuntimeError(
            "Flower port {0} still occupied — stop stray server processes and retry".format(
                cfg["fl_port"]
            )
        )
    return st


def _wait_flower_grpc_ready(port: int, server_pid: int, timeout: float = 45.0) -> None:
    """Wait until our Flower process is listening and gRPC initialized."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(server_pid):
            tail = _server_log_tail(20)
            if "already in use" in tail:
                break
            time.sleep(0.3)
            continue
        tail = _server_log_tail(25)
        if "gRPC server running" in tail and "already in use" not in tail:
            if _port_open("127.0.0.1", port):
                time.sleep(1.0)
                return
        if _port_open("127.0.0.1", port) and _alive(server_pid):
            time.sleep(2.0)
            return
        time.sleep(0.5)
    if not _port_open("127.0.0.1", port):
        raise RuntimeError(
            "Flower gRPC not ready on port {0} within {1}s".format(port, int(timeout))
        )


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        print(json.dumps(start(), indent=2))
    elif cmd == "stop":
        print(json.dumps(stop(), indent=2))
    else:
        print(json.dumps(status(), indent=2))
