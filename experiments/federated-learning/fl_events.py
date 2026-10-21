"""Shared FL visualization state (server + dashboard + edge plugins)."""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path("/tmp/fl_dashboard_state.json")
_lock = threading.Lock()

PHASES = (
    "idle",
    "waiting_clients",
    "broadcast",
    "local_training",
    "upload_weights",
    "aggregating",
    "evaluating",
    "round_complete",
    "finished",
)

BOARD_ALIASES = {
    "board-alpha": "board-alpha",
    "board-beta": "board-beta",
    "board-gamma": "board-gamma",
    "alpha": "board-alpha",
    "beta": "board-beta",
    "gamma": "board-gamma",
}

SCENARIO_CLIENTS = {
    "heart": {
        "board-alpha": {"slug": "alpha", "line": "Clinical cohort A", "csv": "heart_1.csv"},
        "board-beta": {"slug": "beta", "line": "Clinical cohort B", "csv": "heart_2.csv"},
        "board-gamma": {"slug": "gamma", "line": "Clinical cohort C", "csv": "heart_3.csv"},
    },
    "pm": {
        "board-alpha": {"slug": "alpha", "line": "CNC spindle", "csv": "machine_1.csv"},
        "board-beta": {"slug": "beta", "line": "Conveyor motor", "csv": "machine_2.csv"},
        "board-gamma": {"slug": "gamma", "line": "Pump line", "csv": "machine_3.csv"},
    },
}

SCENARIO_UI = {
    "heart": {
        "pill": "Heart Ch.19",
        "subtitle": "3 edge cohorts · federated learning",
        "cloudSubtitle": "Global model · FedAvg",
    },
    "pm": {
        "pill": "Pred. maintenance",
        "subtitle": "3 production lines · federated learning",
        "cloudSubtitle": "Global model · FedAvg",
    },
}


def _empty_state() -> dict[str, Any]:
    return {
        "phase": "idle",
        "round": 0,
        "total_rounds": int(__import__("os").environ.get("FL_ROUNDS", "2")),
        "fl_scenario": "heart",
        "accuracy": [],
        "loss": [],
        "clients": {
            "board-alpha": {"status": "offline", "samples": 0, "last_action": ""},
            "board-beta": {"status": "offline", "samples": 0, "last_action": ""},
            "board-gamma": {"status": "offline", "samples": 0, "last_action": ""},
        },
        "events": [],
        "updated_at": time.time(),
    }


def _load() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_state()


def _json_safe(value: Any) -> Any:
    """Ensure state is serializable in browsers (no NaN/Infinity)."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _save(state: dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    safe = _json_safe(state)
    STATE_PATH.write_text(json.dumps(safe, indent=0, allow_nan=False))


def reset(total_rounds: int | None = None, scenario: str = "heart") -> None:
    with _lock:
        state = _empty_state()
        if total_rounds is not None:
            state["total_rounds"] = total_rounds
        if scenario in SCENARIO_CLIENTS:
            state["fl_scenario"] = scenario
        _save(state)


def _normalize_client(name: str) -> str:
    key = name.lower().strip()
    for token, canonical in BOARD_ALIASES.items():
        if token in key:
            return canonical
    return name


def _push_event(state: dict[str, Any], kind: str, message: str, **extra: Any) -> None:
    evt = {"t": time.time(), "kind": kind, "message": message, **extra}
    state["events"].append(evt)
    state["events"] = state["events"][-80:]


def emit(kind: str, message: str = "", **extra: Any) -> None:
    with _lock:
        state = _load()
        if extra.get("phase") in PHASES:
            state["phase"] = extra["phase"]
        if "round" in extra:
            state["round"] = extra["round"]
        if extra.get("fl_scenario") in SCENARIO_CLIENTS:
            state["fl_scenario"] = extra["fl_scenario"]
        client = extra.get("client")
        if client:
            cid = _normalize_client(str(client))
            if cid in state["clients"]:
                c = state["clients"][cid]
                if extra.get("client_status"):
                    c["status"] = extra["client_status"]
                if extra.get("samples") is not None:
                    c["samples"] = extra["samples"]
                if extra.get("csv_file"):
                    c["csv_file"] = extra["csv_file"]
                if extra.get("fl_scenario") in SCENARIO_CLIENTS:
                    c["fl_scenario"] = extra["fl_scenario"]
                if message:
                    c["last_action"] = message
        if kind == "metrics" and "accuracy" in extra:
            rnd = extra.get("round", state["round"])
            state["accuracy"].append({"round": rnd, "value": extra["accuracy"]})
            if "loss" in extra:
                loss_val = _json_safe(extra["loss"])
                if loss_val is not None:
                    state["loss"].append({"round": rnd, "value": loss_val})
        clean_extra = {k: _json_safe(v) for k, v in extra.items()}
        _push_event(state, kind, message or kind, **clean_extra)
        _save(state)


def _infer_scenario(state: dict[str, Any]) -> str:
    """Derive active lab example from client CSV paths when state is stale."""
    for client in (state.get("clients") or {}).values():
        csv_file = str(client.get("csv_file") or "")
        if "machine_" in csv_file:
            return "pm"
        if "heart_" in csv_file:
            return "heart"
    scenario = state.get("fl_scenario", "heart")
    return scenario if scenario in SCENARIO_UI else "heart"


def snapshot() -> dict[str, Any]:
    with _lock:
        state = _json_safe(_load())
        scenario = _infer_scenario(state)
        state["fl_scenario"] = scenario
        state["scenario_clients"] = SCENARIO_CLIENTS.get(
            scenario, SCENARIO_CLIENTS["heart"]
        )
        ui = dict(SCENARIO_UI.get(scenario, SCENARIO_UI["heart"]))
        ui["clients"] = state["scenario_clients"]
        state["scenario_ui"] = ui
        return state
