#!/usr/bin/env python3
"""HTTP control API for FL server — called from Horizon panel."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request

import fl_server_manager as mgr

app = Flask(__name__)
CONTROL_TOKEN = os.environ.get("FL_CONTROL_TOKEN", "")


def _authorized() -> bool:
    if not CONTROL_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if auth == "Bearer {0}".format(CONTROL_TOKEN):
        return True
    return request.headers.get("X-Fl-Control-Token") == CONTROL_TOKEN


def _cfg_from_request():
    data = request.get_json(silent=True) or {}
    if request.method == "GET":
        data = dict(data)
        data.update(request.args.to_dict())
    mapping = {
        "fl_rounds": data.get("fl_rounds") or data.get("rounds"),
        "fl_scenario": data.get("fl_scenario") or data.get("scenario"),
        "fl_port": data.get("fl_port") or data.get("server_port"),
        "fl_host": data.get("fl_host") or data.get("server_host"),
        "fl_dashboard_port": data.get("fl_dashboard_port") or data.get("dashboard_port"),
        "fl_dashboard_host": data.get("fl_dashboard_host") or data.get("dashboard_host"),
    }
    return {k: v for k, v in mapping.items() if v}


@app.route("/api/fl/status", methods=["GET"])
def api_status():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(mgr.status(_cfg_from_request() or None))


@app.route("/api/fl/start", methods=["POST"])
def api_start():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        return jsonify(mgr.start(_cfg_from_request() or None))
    except Exception as exc:
        return jsonify({"error": str(exc), "running": False}), 500


@app.route("/api/fl/stop", methods=["POST"])
def api_stop():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(mgr.stop(_cfg_from_request() or None))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


def _autostart() -> None:
    """Bring the Flower server + live dashboard up after a (re)start so the demo survives reboots."""
    import threading
    import time

    def _run() -> None:
        time.sleep(3)
        try:
            if not mgr.status().get("running"):
                mgr.start(None)
        except Exception as exc:  # best effort: Horizon can still start it
            print("FL autostart failed: {0}".format(exc), flush=True)

    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    if os.environ.get("FL_AUTOSTART", "1") == "1":
        _autostart()
    host = os.environ.get("FL_CONTROL_HOST", "0.0.0.0")
    port = int(os.environ.get("FL_CONTROL_PORT", "8091"))
    app.run(host=host, port=port, threaded=True, use_reloader=False)
