#!/usr/bin/env python3
"""S4T metrics gateway + provisioner (InfluxDB 1.8, lab)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, request
from influxdb import InfluxDBClient

from registry import RegistryStore

app = Flask(__name__)

HOST = os.environ.get("METRICS_HOST", "0.0.0.0")
PORT = int(os.environ.get("METRICS_PORT", "8093"))
INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
INFLUX_DB = os.environ.get("INFLUX_DB", "s4t_iot")
INFLUX_USER = os.environ.get("INFLUX_USER", "admin")
INFLUX_PASS = os.environ.get("INFLUX_PASSWORD", "admin")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "/app/data/metrics_streams.json")
METRICS_WRITE_URL = os.environ.get(
    "METRICS_WRITE_URL", "http://metrics-gateway:8093/v1/metrics/write"
)

registry = RegistryStore(REGISTRY_PATH, METRICS_WRITE_URL)
_influx: InfluxDBClient | None = None


def _parse_influx_url(url: str) -> tuple[str, int, bool]:
    parsed = urlparse(url)
    host = parsed.hostname or "influxdb"
    port = parsed.port or 8086
    ssl = parsed.scheme == "https"
    return host, port, ssl


def _influx_client() -> InfluxDBClient:
    global _influx
    if _influx is None:
        host, port, ssl = _parse_influx_url(INFLUX_URL)
        _influx = InfluxDBClient(
            host=host,
            port=port,
            username=INFLUX_USER,
            password=INFLUX_PASS,
            database=INFLUX_DB,
            ssl=ssl,
        )
        _influx.create_database(INFLUX_DB)
    return _influx


def _auth_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _public_stream(stream: dict) -> dict:
    return {
        "stream_id": stream.get("stream_id"),
        "measurement": stream.get("measurement"),
        "board_uuid": stream.get("board_uuid"),
        "board_name": stream.get("board_name"),
        "plugin_uuid": stream.get("plugin_uuid"),
        "plugin_name": stream.get("plugin_name"),
        "fleet": stream.get("fleet"),
        "tenant": stream.get("tenant"),
        "field_schema": stream.get("field_schema", []),
        "grafana_dashboard_uid": stream.get("grafana_dashboard_uid"),
        "grafana_panel_url": stream.get("grafana_panel_url"),
        "metrics_url": stream.get("metrics_url"),
        "metrics_stream": stream.get("metrics_stream"),
        "active": stream.get("active", False),
        "last_seen": stream.get("last_seen"),
        "stream_key": stream.get("stream_key"),
    }


def _stream_key(measurement: str, board: str, plugin: str) -> str:
    return "{0}|{1}|{2}".format(measurement or "", board or "", plugin or "")


def _grafana_panel_url(board_name: str, measurement: str) -> str:
    board_slug = board_name or "all"
    return (
        "/horizon/metrics-live/d/s4t-iot-metrics/iot-metrics"
        "?var-board={0}&var-measurement={1}&kiosk=tv".format(board_slug, measurement)
    )


def _registry_lookup() -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for stream in registry.list_streams():
        key = _stream_key(
            stream.get("measurement") or stream.get("stream_id") or "",
            stream.get("board_name") or "",
            stream.get("plugin_name") or "",
        )
        lookup[key] = stream
    return lookup


def _discover_active_streams(window_minutes: int = 15) -> list[dict]:
    window = max(1, min(int(window_minutes), 1440))
    client = _influx_client()
    reg_lookup = _registry_lookup()
    active: list[dict] = []
    seen: set[str] = set()

    try:
        measurements = [
            row.get("name")
            for row in client.query("SHOW MEASUREMENTS").get_points()
            if row.get("name")
        ]
    except Exception:
        measurements = []

    if not measurements:
        return []

    for measurement in measurements:
        safe_meas = measurement.replace('"', '\\"')
        query = (
            'SELECT * FROM "{meas}" WHERE time > now() - {window}m '
            'GROUP BY board, plugin, board_uuid, plugin_uuid ORDER BY time DESC LIMIT 1'
        ).format(meas=safe_meas, window=window)
        try:
            result = client.query(query)
        except Exception:
            continue

        for (_series_name, tags), points in result.items():
            tags = tags or {}
            board = tags.get("board") or ""
            plugin = tags.get("plugin") or ""
            if not board and not plugin:
                continue

            key = _stream_key(measurement, board, plugin)
            if key in seen:
                continue
            seen.add(key)

            last_seen = None
            for point in points:
                last_seen = point.get("time")
                break

            reg = reg_lookup.get(key, {})
            board_uuid = tags.get("board_uuid") or reg.get("board_uuid") or ""
            plugin_uuid = tags.get("plugin_uuid") or reg.get("plugin_uuid") or ""
            board_name = board or reg.get("board_name") or ""
            plugin_name = plugin or reg.get("plugin_name") or ""

            item = {
                "stream_id": measurement,
                "measurement": measurement,
                "board_uuid": board_uuid,
                "board_name": board_name,
                "plugin_uuid": plugin_uuid,
                "plugin_name": plugin_name,
                "fleet": reg.get("fleet") or tags.get("fleet") or "",
                "tenant": reg.get("tenant") or tags.get("tenant") or "lab",
                "field_schema": reg.get("field_schema") or [],
                "grafana_dashboard_uid": reg.get("grafana_dashboard_uid") or "s4t-iot-metrics",
                "grafana_panel_url": reg.get("grafana_panel_url")
                or _grafana_panel_url(board_name, measurement),
                "metrics_url": reg.get("metrics_url") or METRICS_WRITE_URL,
                "metrics_stream": measurement,
                "active": True,
                "last_seen": last_seen,
                "stream_key": key,
            }
            active.append(item)

    active.sort(
        key=lambda s: (
            s.get("board_name") or "",
            s.get("plugin_name") or "",
            s.get("measurement") or "",
        )
    )
    return active


@app.route("/health")
def health():
    try:
        _influx_client().ping()
        influx_ok = True
    except Exception as exc:
        influx_ok = False
        influx_err = str(exc)
    else:
        influx_err = None
    return jsonify(
        {
            "ok": influx_ok,
            "service": "metrics-gateway",
            "influx_db": INFLUX_DB,
            "influx_ok": influx_ok,
            "influx_error": influx_err,
            "streams": len(registry.list_streams()),
        }
    )


@app.route("/v1/streams/provision", methods=["POST"])
def provision():
    payload = request.get_json(silent=True) or {}
    required = ("board_uuid", "plugin_uuid")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return jsonify({"error": "missing fields", "fields": missing}), 400

    stream = registry.provision(payload)
    return jsonify(
        {
            "stream_id": stream["stream_id"],
            "write_token": stream["write_token"],
            "metrics_url": stream["metrics_url"],
            "metrics_token": stream["write_token"],
            "metrics_stream": stream["stream_id"],
            "grafana_dashboard_uid": stream["grafana_dashboard_uid"],
            "grafana_panel_url": stream["grafana_panel_url"],
        }
    )


@app.route("/v1/streams")
def streams_list():
    board_uuid = request.args.get("board_uuid")
    items = [_public_stream(s) for s in registry.list_streams(board_uuid or None)]
    return jsonify({"streams": items})


@app.route("/v1/streams/active")
def streams_active():
    window = request.args.get("window_minutes", "15")
    try:
        window_minutes = int(window)
    except (TypeError, ValueError):
        window_minutes = 15
    items = _discover_active_streams(window_minutes)
    live = [s for s in items if s.get("active")]
    return jsonify(
        {
            "streams": items,
            "live_count": len(live),
            "window_minutes": max(1, min(window_minutes, 1440)),
        }
    )


@app.route("/v1/metrics/write", methods=["POST"])
def metrics_write():
    token = _auth_token()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    stream = registry.find_token(token)
    if not stream:
        return jsonify({"error": "invalid token"}), 403

    body = request.get_json(silent=True) or {}
    fields = body.get("fields")
    if not isinstance(fields, dict) or not fields:
        return jsonify({"error": "fields required"}), 400

    tags = dict(body.get("tags") or {})
    tags.update(
        {
            "board": stream.get("board_name") or "",
            "board_uuid": stream.get("board_uuid") or "",
            "fleet": stream.get("fleet") or "",
            "plugin": stream.get("plugin_name") or "",
            "plugin_uuid": stream.get("plugin_uuid") or "",
            "tenant": stream.get("tenant") or "lab",
        }
    )

    point: dict[str, Any] = {
        "measurement": stream.get("stream_id") or stream.get("measurement"),
        "tags": tags,
        "fields": fields,
    }
    ts = body.get("time")
    if ts:
        point["time"] = ts
    else:
        point["time"] = datetime.utcnow().isoformat()

    try:
        ok = _influx_client().write_points([point])
    except Exception as exc:
        return jsonify({"error": "influx write failed", "detail": str(exc)}), 502

    if not ok:
        return jsonify({"error": "influx write returned false"}), 502
    return jsonify({"ok": True, "stream_id": stream.get("stream_id")})


@app.route("/v1/metrics/recent")
def metrics_recent():
    stream_id = request.args.get("stream_id")
    if not stream_id:
        return jsonify({"error": "stream_id required"}), 400
    limit = min(int(request.args.get("limit", "20")), 100)
    board = request.args.get("board", "")

    measurement = stream_id.replace('"', "")
    if board:
        query = (
            'SELECT * FROM "{0}" WHERE "board" = \'{1}\' ORDER BY time DESC LIMIT {2}'
        ).format(measurement, board.replace("'", "\\'"), limit)
    else:
        query = 'SELECT * FROM "{0}" ORDER BY time DESC LIMIT {1}'.format(measurement, limit)
    try:
        result = _influx_client().query(query)
        points = list(result.get_points())
    except Exception as exc:
        return jsonify({"error": "query failed", "detail": str(exc)}), 502

    return jsonify({"stream_id": stream_id, "points": points})


if __name__ == "__main__":
    _influx_client()
    app.run(host=HOST, port=PORT, threaded=True)
