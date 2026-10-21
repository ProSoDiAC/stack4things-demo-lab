#!/usr/bin/env python3
"""S4T Federated Learning live dashboard — Flask + SSE."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fl_events  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.route("/")
@app.route("/fl/")
def index():
    embed = request.args.get("embed") == "1"
    return render_template("index.html", embed=embed)


@app.route("/api/state")
def api_state():
    return jsonify(fl_events.snapshot())


@app.route("/api/events")
def api_events_stream():
    def generate():
        last_ts = 0.0
        while True:
            state = fl_events.snapshot()
            ts = state.get("updated_at", 0)
            if ts > last_ts:
                last_ts = ts
                yield f"data: {json.dumps(state)}\n\n"
            time.sleep(0.4)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/client-event", methods=["POST"])
def client_event():
    data = request.get_json(force=True, silent=True) or {}
    kind = data.get("kind", "client")
    client = data.get("client", "unknown")
    message = data.get("message", kind)
    phase = data.get("phase")
    extra = {k: v for k, v in data.items() if k not in ("kind", "client", "message", "phase")}
    if phase:
        extra["phase"] = phase
    if data.get("client_status"):
        extra["client_status"] = data["client_status"]
    fl_events.emit(kind, message, client=client, **extra)
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def reset_state():
    body = request.get_json(silent=True) or {}
    rounds = int(body.get("total_rounds", os.environ.get("FL_ROUNDS", "2")))
    scenario = body.get("fl_scenario", os.environ.get("FL_SCENARIO", "heart"))
    fl_events.reset(rounds, scenario=scenario)
    return jsonify({"ok": True})


def main() -> None:
    host = os.environ.get("FL_DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("FL_DASHBOARD_PORT", "8090"))
    fl_events.reset(int(os.environ.get("FL_ROUNDS", "2")))
    print(f"FL dashboard http://{host}:{port}/  (Horizon: /horizon/fl/)")
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
