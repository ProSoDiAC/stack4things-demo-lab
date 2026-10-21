#!/usr/bin/env python3
"""Lab HTTP proxy: tail Lightning-Rod container logs (auto-discovers board mapping)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from flask import Flask, jsonify, request

app = Flask(__name__)

# Fallback when LR settings.json is not yet readable (registered-only boards)
LR_CONTAINER_BY_BOARD = {
    "board-alpha": "lightning-rod",
    "board-beta": "lightning-rod-2",
    "board-gamma": "lightning-rod-3",
    "board-delta": "lightning-rod-4",
    "board-epsilon": "lightning-rod-5",
    "board-zeta": "lightning-rod-6",
}

DEFAULT_TAIL = int(os.environ.get("LR_LOG_TAIL", "40"))
MAX_TAIL = int(os.environ.get("LR_LOG_MAX_TAIL", "200"))
DOCKER_BIN = os.environ.get("DOCKER_BIN", "docker")
MAP_CACHE_TTL = int(os.environ.get("LR_MAP_CACHE_TTL", "45"))

# Dynamic LR provisioning (Create Lab Board + LR)
LR_IMAGE = os.environ.get("LR_IMAGE", "docker.io/mdslab/lrod:compose")
LR_NETWORK = os.environ.get("LR_NETWORK", "s4t_s4t")
LR_VOLUME_PREFIX = os.environ.get("LR_VOLUME_PREFIX", "s4t_lr")
LR_PORT_START = int(os.environ.get("LR_PORT_START", "1480"))
LR_MAX_DYNAMIC = int(os.environ.get("LR_MAX_DYNAMIC", "12"))
LR_STATIC_MAX_INDEX = int(os.environ.get("LR_STATIC_MAX_INDEX", "6"))  # lightning-rod-6
LR_WAMP_DEFAULT = os.environ.get("LR_WAMP_URL", "wss://crossbar:8181")
TRAINING_ROOT = os.environ.get(
    "TRAINING_ROOT",
    "/lab",
)
LR_METRICS_HOST = os.environ.get(
    "LR_METRICS_HOST",
    os.path.join(TRAINING_ROOT, "experiments/metrics/s4t_metrics.py"),
)
LR_OPT_FL_HOST = os.environ.get(
    "LR_OPT_FL_HOST",
    os.path.join(TRAINING_ROOT, "experiments/federated-learning/opt-fl"),
)
LR_LAB_DIR = os.environ.get("LR_LAB_DIR", "")
LR_FL_PYTHON_VOL = os.environ.get("LR_FL_PYTHON_VOL", "s4t_lr_fl_python")

_map_cache: dict = {"ts": 0.0, "by_name": {}, "by_uuid": {}}
_provision_lock = False


def _list_lr_containers() -> list[str]:
    try:
        out = subprocess.check_output(
            [DOCKER_BIN, "ps", "--format", "{{.Names}}"],
            stderr=subprocess.STDOUT,
            timeout=15,
        )
    except Exception:
        return []
    names = []
    for line in out.decode("utf-8", "replace").splitlines():
        name = line.strip()
        if name == "lightning-rod" or name.startswith("lightning-rod-"):
            names.append(name)
    return sorted(names, key=lambda n: (n != "lightning-rod", n))


def _board_from_container(container: str) -> tuple[str, str]:
    script = (
        "import json; "
        "b=json.load(open('/etc/iotronic/settings.json')).get('iotronic',{}).get('board',{}); "
        "print((b.get('name') or ''), (b.get('uuid') or ''))"
    )
    try:
        out = subprocess.check_output(
            [DOCKER_BIN, "exec", container, "python3", "-c", script],
            stderr=subprocess.STDOUT,
            timeout=12,
        )
        text = out.decode("utf-8", "replace").strip()
        if not text:
            return "", ""
        # uuid has no spaces; name is single token in lab
        parts = text.split()
        if len(parts) >= 2:
            return parts[0], parts[1]
        return parts[0], ""
    except Exception:
        return "", ""


def discover_board_map(refresh: bool = False) -> tuple[dict, dict]:
    now = time.time()
    if not refresh and now - _map_cache["ts"] < MAP_CACHE_TTL:
        return _map_cache["by_name"], _map_cache["by_uuid"]

    by_name: dict[str, str] = dict(LR_CONTAINER_BY_BOARD)
    by_uuid: dict[str, str] = {}
    for container in _list_lr_containers():
        name, uuid = _board_from_container(container)
        if name:
            by_name[name] = container
        if uuid:
            by_uuid[uuid] = container

    _map_cache["ts"] = now
    _map_cache["by_name"] = by_name
    _map_cache["by_uuid"] = by_uuid
    return by_name, by_uuid


def resolve_container(board_name: str | None = None, board_uuid: str | None = None) -> str | None:
    by_name, by_uuid = discover_board_map()
    if board_uuid and board_uuid in by_uuid:
        return by_uuid[board_uuid]
    if board_name and board_name in by_name:
        return by_name[board_name]
    return None


# LR writes oslo/plugin logs here; docker stdout often has only boot/Flask noise.
LR_LOG_FILE = "/var/log/iotronic/lightning-rod.log"


def _tail_container(container: str, tail: int, grep: str | None) -> list[str]:
    """Prefer Lightning-Rod log file (PluginCall, LOG.info); fall back to docker logs."""
    lines: list[str] = []
    file_cmd = [
        DOCKER_BIN, "exec", container, "sh", "-c",
        "if [ -f '{0}' ]; then tail -n {1} '{0}'; else exit 2; fi".format(
            LR_LOG_FILE, int(tail)
        ),
    ]
    try:
        out = subprocess.check_output(file_cmd, stderr=subprocess.STDOUT, timeout=30)
        lines = out.decode("utf-8", "replace").splitlines()
    except subprocess.CalledProcessError:
        lines = []
    except Exception:
        lines = []

    if not lines:
        cmd = [DOCKER_BIN, "logs", "--tail", str(tail), container]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=30)
        except subprocess.CalledProcessError as exc:
            text = exc.output.decode("utf-8", "replace") if getattr(exc, "output", None) else str(exc)
            return ["[error] docker logs failed: {0}".format(text.strip())]
        except Exception as exc:
            return ["[error] {0}".format(exc)]
        lines = out.decode("utf-8", "replace").splitlines()

    if grep:
        pat = re.compile(grep, re.I)
        lines = [ln for ln in lines if pat.search(ln)]
    return lines[-tail:]


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/lr-map", methods=["GET"])
def api_lr_map():
    refresh = request.args.get("refresh") == "1"
    by_name, by_uuid = discover_board_map(refresh=refresh)
    rows = [
        {"board_name": name, "board_uuid": uid, "container": by_uuid.get(uid) or by_name.get(name)}
        for name, container in sorted(by_name.items())
        for uid in [next((u for u, c in by_uuid.items() if c == container), "")]
    ]
    # simpler output
    mapping = []
    seen = set()
    for container in _list_lr_containers():
        name, uuid = _board_from_container(container)
        key = (name, uuid, container)
        if key in seen:
            continue
        seen.add(key)
        mapping.append({
            "board_name": name or None,
            "board_uuid": uuid or None,
            "container": container,
        })
    return jsonify({"mapping": mapping, "by_name": by_name, "by_uuid": by_uuid})


def _run(cmd: list[str], timeout: int = 120) -> str:
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
    return out.decode("utf-8", "replace")


def _lr_index(name: str) -> int | None:
    if name == "lightning-rod":
        return 1
    m = re.match(r"^lightning-rod-(\d+)$", name)
    if not m:
        return None
    return int(m.group(1))


def _list_all_lr_names() -> list[str]:
    """Running + stopped LR containers (for name/port allocation)."""
    try:
        out = _run([DOCKER_BIN, "ps", "-a", "--format", "{{.Names}}"], timeout=15)
    except Exception:
        return _list_lr_containers()
    names = []
    for line in out.splitlines():
        name = line.strip()
        if name == "lightning-rod" or name.startswith("lightning-rod-"):
            names.append(name)
    return names


def _used_host_ports() -> set[int]:
    ports: set[int] = set()
    try:
        out = _run(
            [DOCKER_BIN, "ps", "-a", "--format", "{{.Names}}\t{{.Ports}}"],
            timeout=15,
        )
    except Exception:
        return ports
    for line in out.splitlines():
        # e.g. 0.0.0.0:1477->1474/tcp
        for m in re.finditer(r"(?:0\.0\.0\.0|::):(\d+)->1474/tcp", line):
            ports.add(int(m.group(1)))
    return ports


def _next_lr_slot() -> tuple[int, str, int]:
    """Return (index, container_name, host_port) for a new dynamic LR."""
    names = _list_all_lr_names()
    indices = []
    for name in names:
        idx = _lr_index(name)
        if idx is not None:
            indices.append(idx)
    dynamic_count = sum(1 for i in indices if i > LR_STATIC_MAX_INDEX)
    if dynamic_count >= LR_MAX_DYNAMIC:
        raise RuntimeError(
            "Dynamic LR limit reached ({0}). Remove unused lightning-rod-N first.".format(
                LR_MAX_DYNAMIC
            )
        )
    next_idx = max([LR_STATIC_MAX_INDEX] + indices) + 1
    used_ports = _used_host_ports()
    port = LR_PORT_START
    while port in used_ports:
        port += 1
        if port > LR_PORT_START + 200:
            raise RuntimeError("No free host port for Lightning-Rod UI")
    return next_idx, "lightning-rod-{0}".format(next_idx), port


def _volume_exists(name: str) -> bool:
    try:
        _run([DOCKER_BIN, "volume", "inspect", name], timeout=10)
        return True
    except Exception:
        return False


def _ensure_volumes(idx: int) -> dict[str, str]:
    mapping = {
        "var": "{0}{1}_var".format(LR_VOLUME_PREFIX, idx),
        "le": "{0}{1}_le".format(LR_VOLUME_PREFIX, idx),
        "nginx": "{0}{1}_nginx".format(LR_VOLUME_PREFIX, idx),
        "confs": "{0}{1}_confs".format(LR_VOLUME_PREFIX, idx),
        "data": "{0}{1}_data".format(LR_VOLUME_PREFIX, idx),
    }
    for vol in mapping.values():
        if not _volume_exists(vol):
            _run([DOCKER_BIN, "volume", "create", vol], timeout=30)
    return mapping


def _docker_run_lr(container: str, host_port: int, volumes: dict[str, str]) -> None:
    cmd = [
        DOCKER_BIN, "run", "-d",
        "--name", container,
        "--restart", "unless-stopped",
        "--privileged",
        "--network", LR_NETWORK,
        "-p", "{0}:1474".format(host_port),
        "-v", "{0}:/var/lib/iotronic".format(volumes["var"]),
        "-v", "{0}:/etc/letsencrypt".format(volumes["le"]),
        "-v", "{0}:/etc/nginx".format(volumes["nginx"]),
        "-v", "{0}:/etc/iotronic".format(volumes["confs"]),
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", "{0}:/opt/data".format(volumes["data"]),
        "-l", "s4t.lab.dynamic_lr=1",
        "-l", "s4t.lab.host_port={0}".format(host_port),
    ]
    if LR_METRICS_HOST:
        cmd.extend(["-v", "{0}:/opt/lab/s4t_metrics.py:ro".format(LR_METRICS_HOST)])
    if LR_OPT_FL_HOST:
        # Host path: do not os.path.isdir here (proxy may not see the host FS).
        cmd.extend(["-v", "{0}:/opt/fl:ro".format(LR_OPT_FL_HOST)])
    if _volume_exists(LR_FL_PYTHON_VOL):
        cmd.extend(["-v", "{0}:/opt/fl-python".format(LR_FL_PYTHON_VOL)])

    if LR_LAB_DIR:
        # Host path of ./entrypoints: same entrypoint as the compose-managed Lightning-Rods
        # (wstun host fix, shared pip target, optional sshd).
        cmd.extend(["-v", "{0}:/opt/s4t-lab:ro".format(LR_LAB_DIR)])
        cmd.extend(["-e", "LAB_SSHD=" + os.environ.get("LAB_SSHD", "1")])
        cmd.extend(["--entrypoint", "/bin/bash", LR_IMAGE, "/opt/s4t-lab/lr-entrypoint.sh"])
    else:
        entry = (
            "for d in /usr/local/lib/python3*/site-packages; do "
            "echo /opt/fl-python > \"$d/z_fl_lab.pth\"; done; "
            "sed -i \"s|self\\.wstun_ip *= .*|self.wstun_ip = \\\"iotronic-wstun\\\"|\" "
            "/usr/local/lib/python3*/site-packages/iotronic_lightningrod/modules/service_manager.py "
            "&& exec startLR"
        )
        cmd.extend(["--entrypoint", "/bin/sh", LR_IMAGE, "-c", entry])
    _run(cmd, timeout=120)


def _lr_base(container: str, host_port: int) -> str:
    """The proxy runs inside the compose network: reach the new LR by container name, not via the host port."""
    return "http://{0}:1474".format(container)


def _wait_lr_http(container: str, host_port: int, timeout: float = 90.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    url = _lr_base(container, host_port) + "/config"
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status in (200, 302, 401, 403):
                    return
        except Exception as exc:
            last_err = str(exc)
        time.sleep(2)
    raise RuntimeError(
        "Lightning-Rod UI on :{0} not ready ({1})".format(host_port, last_err)
    )


def _configure_lr(container: str, host_port: int, registration_code: str, wamp_url: str, hostname: str) -> None:
    """POST first-boot config form (no login required while status=first_boot)."""
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        "urlwagent": wamp_url,
        "code": registration_code,
        "hostname": hostname or "",
        "reg_btn": "CONFIGURE",
    }).encode("utf-8")
    req = urllib.request.Request(
        _lr_base(container, host_port) + "/config",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
    except Exception as exc:
        # CONFIGURE may restart LR and drop the connection — treat as soft OK
        msg = str(exc).lower()
        if "reset" in msg or "timed out" in msg or "eof" in msg or "refused" in msg:
            time.sleep(5)
            return
        raise RuntimeError("LR configure failed: {0}".format(exc))


def _wait_lr_operative(container: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = _run(
                [
                    DOCKER_BIN, "exec", container, "python3", "-c",
                    "import json; b=json.load(open('/etc/iotronic/settings.json'))"
                    ".get('iotronic',{}).get('board',{}); "
                    "print(b.get('status',''), b.get('code',''))",
                ],
                timeout=12,
            ).strip()
            status = out.split(None, 1)[0] if out else ""
            if status == "operative":
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def provision_lightning_rod(
    board_name: str,
    registration_code: str,
    wamp_url: str | None = None,
) -> dict:
    global _provision_lock
    if _provision_lock:
        raise RuntimeError("Another LR provision is already running")
    _provision_lock = True
    container = ""
    host_port = 0
    try:
        wamp_url = (wamp_url or LR_WAMP_DEFAULT).strip() or LR_WAMP_DEFAULT
        board_name = (board_name or "").strip()
        registration_code = (registration_code or "").strip()
        if not board_name or not registration_code:
            raise RuntimeError("board_name and registration_code are required")

        # Refuse if board already mapped to a running LR
        by_name, _ = discover_board_map(refresh=True)
        if board_name in by_name and by_name[board_name] in _list_lr_containers():
            raise RuntimeError(
                "Board {0} already bound to {1}".format(board_name, by_name[board_name])
            )

        idx, container, host_port = _next_lr_slot()
        volumes = _ensure_volumes(idx)
        _docker_run_lr(container, host_port, volumes)
        _wait_lr_http(container, host_port, timeout=90)
        time.sleep(2)
        _configure_lr(container, host_port, registration_code, wamp_url, board_name)
        operative = _wait_lr_operative(container, timeout=90)
        discover_board_map(refresh=True)
        return {
            "ok": True,
            "board_name": board_name,
            "container": container,
            "host_port": host_port,
            "volumes": volumes,
            "wamp_url": wamp_url,
            "operative": operative,
            "lr_url": "http://127.0.0.1:{0}".format(host_port),
        }
    except Exception:
        # Best-effort cleanup of a brand-new container that never registered
        if container:
            try:
                status = _run(
                    [DOCKER_BIN, "inspect", "-f", "{{.State.Status}}", container],
                    timeout=10,
                ).strip()
                # keep running containers for debugging; only remove if create failed early
                if status and host_port and not _wait_lr_operative(container, timeout=1):
                    pass
            except Exception:
                pass
        raise
    finally:
        _provision_lock = False


@app.route("/provision", methods=["POST"])
def api_provision():
    """Create Lightning-Rod container + volumes and register with board code."""
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    if not payload and request.form:
        payload = request.form.to_dict()
    try:
        result = provision_lightning_rod(
            board_name=payload.get("board_name", ""),
            registration_code=payload.get("registration_code")
            or payload.get("code", ""),
            wamp_url=payload.get("wamp_url"),
        )
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def deprovision_lightning_rod(
    board_name: str = "",
    board_uuid: str = "",
    container: str = "",
    remove_volumes: bool = True,
) -> dict:
    """Stop/remove a dynamic LR bound to a lab board (never touches alpha-zeta)."""
    board_name = (board_name or "").strip()
    board_uuid = (board_uuid or "").strip()
    container = (container or "").strip()

    by_name, by_uuid = discover_board_map(refresh=True)
    if not container:
        if board_name and board_name in by_name:
            container = by_name[board_name]
        elif board_uuid and board_uuid in by_uuid:
            container = by_uuid[board_uuid]

    if not container:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no Lightning-Rod container mapped to this board",
            "board_name": board_name,
            "board_uuid": board_uuid,
        }

    idx = _lr_index(container)
    static_names = {"lightning-rod"} | {
        "lightning-rod-{0}".format(i) for i in range(2, LR_STATIC_MAX_INDEX + 1)
    }
    # Protect compose static boards (alpha-zeta => lightning-rod .. lightning-rod-6)
    if container in static_names or (idx is not None and idx <= LR_STATIC_MAX_INDEX):
        return {
            "ok": True,
            "skipped": True,
            "reason": "refusing to remove static LR {0}".format(container),
            "container": container,
        }

    # Prefer dynamic label when present; allow named manual LRs without numeric index
    try:
        labels = _run(
            [
                DOCKER_BIN,
                "inspect",
                "-f",
                '{{index .Config.Labels "s4t.lab.dynamic_lr"}}',
                container,
            ],
            timeout=10,
        ).strip()
    except Exception:
        labels = ""

    if labels and labels not in ("1", "true", "True"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "container not marked dynamic_lr",
            "container": container,
        }

    _run([DOCKER_BIN, "rm", "-f", container], timeout=60)
    removed_vols = []
    if remove_volumes:
        # Numeric dynamic slots use <project>_lrN_*; manual names use {container}_*
        vol_candidates = []
        if idx is not None and idx > LR_STATIC_MAX_INDEX:
            vol_candidates.extend(_ensure_volumes(idx).values())
        for s in ("var", "le", "nginx", "confs", "data"):
            vol_candidates.append("{0}_{1}".format(container, s))
        for vol in sorted(set(vol_candidates)):
            try:
                _run([DOCKER_BIN, "volume", "rm", "-f", vol], timeout=30)
                removed_vols.append(vol)
            except Exception:
                pass

    discover_board_map(refresh=True)
    return {
        "ok": True,
        "board_name": board_name,
        "board_uuid": board_uuid,
        "container": container,
        "removed_volumes": removed_vols,
    }


@app.route("/deprovision", methods=["POST"])
def api_deprovision():
    """Remove dynamic Lightning-Rod for a board (Create LR Container teardown)."""
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    if not payload and request.form:
        payload = request.form.to_dict()
    try:
        result = deprovision_lightning_rod(
            board_name=payload.get("board_name", ""),
            board_uuid=payload.get("board_uuid", "") or payload.get("uuid", ""),
            container=payload.get("container", ""),
            remove_volumes=str(payload.get("remove_volumes", "1")).lower()
            not in ("0", "false", "no"),
        )
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/provision/status", methods=["GET"])
def api_provision_status():
    names = _list_all_lr_names()
    dynamic = []
    for name in names:
        idx = _lr_index(name)
        if idx is None or idx <= LR_STATIC_MAX_INDEX:
            continue
        dynamic.append({"container": name, "index": idx})
    return jsonify({
        "ok": True,
        "dynamic_count": len(dynamic),
        "max_dynamic": LR_MAX_DYNAMIC,
        "next_port_hint": LR_PORT_START,
        "used_ports": sorted(_used_host_ports()),
        "dynamic": dynamic,
        "busy": _provision_lock,
    })


@app.route("/api/lr-logs", methods=["GET"])
def api_lr_logs():
    board_names = [b.strip() for b in request.args.get("boards", "").split(",") if b.strip()]
    board_uuids = [u.strip() for u in request.args.get("board_uuids", "").split(",") if u.strip()]
    tail = min(max(int(request.args.get("tail", DEFAULT_TAIL)), 1), MAX_TAIL)
    grep = request.args.get("grep") or None
    refresh = request.args.get("refresh") == "1"
    if refresh:
        discover_board_map(refresh=True)

    result = {}
    keys = []
    for name in board_names:
        keys.append(("name", name))
    for uid in board_uuids:
        keys.append(("uuid", uid))

    for kind, key in keys:
        container = resolve_container(
            board_name=key if kind == "name" else None,
            board_uuid=key if kind == "uuid" else None,
        )
        result_key = key
        if not container:
            result[result_key] = {
                "container": None,
                "lines": [
                    "[warn] no Lightning-Rod container found for this board. "
                    "Register the board on an LR instance first."
                ],
            }
            continue
        result[result_key] = {
            "container": container,
            "lines": _tail_container(container, tail, grep),
        }
    return jsonify({"boards": result, "tail": tail})


def _collect_lr_network(container: str) -> dict:
    """Gather interface / IP / route info from an LR container."""
    info: dict = {
        "container": container,
        "hostname": None,
        "interfaces": [],
        "routes": [],
        "dns": [],
        "host_ports": [],
        "error": None,
    }
    try:
        labels = _run(
            [
                DOCKER_BIN, "inspect",
                "--format",
                "{{index .Config.Labels \"s4t.lab.host_port\"}} {{range $p,$c := .NetworkSettings.Ports}}{{$p}} {{end}}",
                container,
            ],
            timeout=10,
        ).strip()
        # Prefer published 1474/tcp host port
        ports_out = _run(
            [DOCKER_BIN, "port", container, "1474/tcp"],
            timeout=10,
        ).strip()
        if ports_out:
            # e.g. 0.0.0.0:1474
            for line in ports_out.splitlines():
                if ":" in line:
                    info["host_ports"].append(line.strip())
    except Exception:
        pass

    try:
        info["hostname"] = _run(
            [DOCKER_BIN, "exec", container, "hostname"], timeout=8
        ).strip()
    except Exception:
        pass

    # Interfaces via ip -j addr
    try:
        raw = _run(
            [DOCKER_BIN, "exec", container, "ip", "-j", "addr"], timeout=12
        )
        addrs = json.loads(raw)
        interfaces = []
        for iface in addrs:
            if not isinstance(iface, dict):
                continue
            entry = {
                "name": iface.get("ifname") or "",
                "mac": iface.get("address") or "",
                "state": iface.get("operstate") or "",
                "mtu": iface.get("mtu"),
                "flags": iface.get("flags") or [],
                "ipv4": [],
                "ipv6": [],
            }
            for a in iface.get("addr_info") or []:
                fam = a.get("family")
                row = {
                    "addr": a.get("local") or "",
                    "prefix": a.get("prefixlen"),
                    "broadcast": a.get("broadcast") or "",
                    "scope": a.get("scope") or "",
                }
                if fam == "inet":
                    entry["ipv4"].append(row)
                elif fam == "inet6":
                    entry["ipv6"].append(row)
            interfaces.append(entry)
        info["interfaces"] = interfaces
    except Exception as exc:
        info["error"] = "ip addr failed: {0}".format(exc)
        try:
            info["raw_ip_addr"] = _run(
                [DOCKER_BIN, "exec", container, "ip", "addr"], timeout=12
            )
        except Exception as exc2:
            info["error"] = "{0}; fallback: {1}".format(info["error"], exc2)

    # Routes
    try:
        raw = _run(
            [DOCKER_BIN, "exec", container, "ip", "-j", "route"], timeout=12
        )
        routes = json.loads(raw)
        parsed = []
        for r in routes:
            if not isinstance(r, dict):
                continue
            parsed.append({
                "dst": r.get("dst") or "default",
                "gateway": r.get("gateway") or "",
                "dev": r.get("dev") or "",
                "protocol": r.get("protocol") or "",
                "metric": r.get("metric"),
                "prefsrc": r.get("prefsrc") or "",
            })
        info["routes"] = parsed
    except Exception:
        try:
            info["raw_routes"] = _run(
                [DOCKER_BIN, "exec", container, "ip", "route"], timeout=12
            )
        except Exception:
            pass

    # DNS resolvers
    try:
        resolv = _run(
            [DOCKER_BIN, "exec", container, "cat", "/etc/resolv.conf"],
            timeout=8,
        )
        dns = []
        for line in resolv.splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2:
                    dns.append(parts[1])
        info["dns"] = dns
    except Exception:
        pass

    return info


@app.route("/api/lr-network", methods=["GET"])
def api_lr_network():
    """Network interfaces, IPs, routes for one Lightning-Rod board."""
    board_name = (request.args.get("board") or request.args.get("boards") or "").strip()
    board_uuid = (request.args.get("board_uuid") or request.args.get("board_uuids") or "").strip()
    # allow comma lists but use first
    if "," in board_name:
        board_name = board_name.split(",", 1)[0].strip()
    if "," in board_uuid:
        board_uuid = board_uuid.split(",", 1)[0].strip()
    refresh = request.args.get("refresh") == "1"
    if refresh:
        discover_board_map(refresh=True)

    container = resolve_container(
        board_name=board_name or None,
        board_uuid=board_uuid or None,
    )
    if not container:
        return jsonify({
            "ok": False,
            "container": None,
            "board_name": board_name or None,
            "board_uuid": board_uuid or None,
            "error": "No Lightning-Rod container found for this board.",
            "interfaces": [],
            "routes": [],
            "dns": [],
        }), 404

    data = _collect_lr_network(container)
    data["ok"] = data.get("error") is None
    data["board_name"] = board_name or None
    data["board_uuid"] = board_uuid or None
    return jsonify(data)


if __name__ == "__main__":
    host = os.environ.get("LR_LOG_PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("LR_LOG_PROXY_PORT", "8092"))
    app.run(host=host, port=port, threaded=True, use_reloader=False)
