"""Stream registry for S4T metrics gateway (JSON file persistence)."""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any

_lock = threading.Lock()


def _empty_registry() -> dict:
    return {"streams": []}


def load_registry(path: str) -> dict:
    if not os.path.exists(path):
        return _empty_registry()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "streams" not in data:
            return _empty_registry()
        return data
    except (OSError, ValueError, TypeError):
        return _empty_registry()


def save_registry(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def find_by_token(registry: dict, token: str) -> dict | None:
    for stream in registry.get("streams", []):
        if stream.get("write_token") == token:
            return stream
    return None


def list_streams(registry: dict, board_uuid: str | None = None) -> list[dict]:
    streams = registry.get("streams", [])
    if not board_uuid:
        return list(streams)
    return [s for s in streams if s.get("board_uuid") == board_uuid]


def provision_stream(registry: dict, payload: dict, metrics_write_url: str) -> dict:
    board_uuid = payload.get("board_uuid", "")
    board_name = payload.get("board_name", "")
    plugin_uuid = payload.get("plugin_uuid", "")
    plugin_name = payload.get("plugin_name", "")
    measurement = payload.get("measurement") or "environmental_data"
    field_schema = payload.get("field_schema") or []
    fleet = payload.get("fleet") or ""
    stream_id = measurement

    streams = registry.setdefault("streams", [])
    existing = None
    for stream in streams:
        if (
            stream.get("board_uuid") == board_uuid
            and stream.get("plugin_uuid") == plugin_uuid
            and stream.get("stream_id") == stream_id
        ):
            existing = stream
            break

    if existing:
        existing.update(
            {
                "board_name": board_name,
                "plugin_name": plugin_name,
                "field_schema": field_schema,
                "fleet": fleet,
            }
        )
        stream = existing
    else:
        stream = {
            "stream_id": stream_id,
            "measurement": measurement,
            "board_uuid": board_uuid,
            "board_name": board_name,
            "plugin_uuid": plugin_uuid,
            "plugin_name": plugin_name,
            "fleet": fleet,
            "tenant": payload.get("tenant") or "lab",
            "write_token": str(uuid.uuid4()),
            "field_schema": field_schema,
        }
        streams.append(stream)

    board_slug = board_name or board_uuid or "all"
    stream["metrics_url"] = metrics_write_url
    stream["grafana_dashboard_uid"] = "s4t-iot-metrics"
    stream["grafana_panel_url"] = (
        "/horizon/metrics-live/d/s4t-iot-metrics/iot-metrics"
        "?var-board={0}&var-measurement={1}&kiosk=tv".format(board_slug, stream_id)
    )
    stream["metrics_token"] = stream["write_token"]
    stream["metrics_stream"] = stream_id
    return stream


class RegistryStore:
    def __init__(self, path: str, metrics_write_url: str):
        self.path = path
        self.metrics_write_url = metrics_write_url

    def load(self) -> dict:
        with _lock:
            return load_registry(self.path)

    def save(self, data: dict) -> None:
        with _lock:
            save_registry(self.path, data)

    def provision(self, payload: dict) -> dict:
        with _lock:
            data = load_registry(self.path)
            stream = provision_stream(data, payload, self.metrics_write_url)
            save_registry(self.path, data)
            return dict(stream)

    def find_token(self, token: str) -> dict | None:
        with _lock:
            return find_by_token(load_registry(self.path), token)

    def list_streams(self, board_uuid: str | None = None) -> list[dict]:
        with _lock:
            return list_streams(load_registry(self.path), board_uuid)
