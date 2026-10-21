# -*- coding: utf-8 -*-
"""Default FL client board mapping and parametric lab settings."""

import json
import os

FL_PLUGIN_PATH = os.environ.get(
    "FL_PLUGIN_SOURCE", "/opt/fl_lab/fl_client_plugin.py"
)
FL_DOCKER_GW = os.environ.get("FL_DOCKER_GW", "fl-control")
FL_SERVER_PORT = os.environ.get("FL_PORT", "8087")
FL_DASHBOARD_PORT = os.environ.get("FL_DASHBOARD_PORT", "8090")

# Two cloud plugins (same LR source code) - pick example via Cloud plugin dropdown.
FL_PLUGIN_HEART = "fl-client-heart"
FL_PLUGIN_PM = "fl-client-pm"
FL_LAB_PLUGIN_NAMES = (FL_PLUGIN_HEART, FL_PLUGIN_PM)
FL_SHARED_PLUGIN_NAME = FL_PLUGIN_HEART  # legacy alias
FL_LEGACY_PLUGIN_NAMES = ("fl-client",)

PLUGIN_SCENARIO = {
    FL_PLUGIN_HEART: "heart",
    FL_PLUGIN_PM: "pm",
    "fl-client": "heart",
}

BOARD_INDEX = {
    "board-alpha": 1,
    "board-beta": 2,
    "board-gamma": 3,
}

LAB_BOARD_NAMES = frozenset(BOARD_INDEX.keys())

FL_SCENARIOS = {
    "heart": {
        "label": "Heart disease classification",
        "short": "Heart disease",
        "plugin_name": FL_PLUGIN_HEART,
        "csv_prefix": "heart",
        "test_csv": "data_test_heart.csv",
        "dashboard_subtitle": "Clinical cohorts / federated diagnosis / 3 edge sites",
        "cloud_subtitle": "Global clinical model / FedAvg",
        "metric_title": "Diagnosis prediction (global model)",
        "metric_hint": "Tabular clinical features - raw patient data stays on each board",
        "metric_label": "diagnosis accuracy",
        "server_banner": "Heart disease FL - 3 edge cohorts",
        "eval_message": "diagnosis accuracy",
        "clients": {
            "board-alpha": {"line": "Clinical cohort A", "csv": "heart_1.csv"},
            "board-beta": {"line": "Clinical cohort B", "csv": "heart_2.csv"},
            "board-gamma": {"line": "Clinical cohort C", "csv": "heart_3.csv"},
        },
    },
    "pm": {
        "label": "Predictive maintenance",
        "short": "Pred. maintenance",
        "plugin_name": FL_PLUGIN_PM,
        "csv_prefix": "machine",
        "test_csv": "data_test_pm.csv",
        "dashboard_subtitle": "Predictive maintenance / failure prediction / 3 production lines",
        "cloud_subtitle": "Global failure model / FedAvg",
        "metric_title": "Failure prediction (global model)",
        "metric_hint": "Vibration / temperature / motor current - CSVs stay on each line",
        "metric_label": "detection accuracy",
        "server_banner": "Predictive maintenance FL - 3 production lines",
        "eval_message": "failure detection accuracy",
        "clients": {
            "board-alpha": {"line": "CNC spindle", "csv": "machine_1.csv"},
            "board-beta": {"line": "Conveyor motor", "csv": "machine_2.csv"},
            "board-gamma": {"line": "Pump line", "csv": "machine_3.csv"},
        },
    },
}

DEFAULT_SCENARIO = "heart"

SESSION_GLOBAL_KEY = "fl_global_config"
LAB_CONFIG_PATH = os.environ.get(
    "FL_LAB_CONFIG", "/opt/fl_lab_run/lab_config.json"
)

GLOBAL_PARAM_KEYS = (
    "fl_rounds",
    "server_host",
    "server_port",
    "dashboard_host",
    "dashboard_port",
)


def default_global_config():
    return {
        "server_host": FL_DOCKER_GW,
        "server_port": FL_SERVER_PORT,
        "dashboard_host": FL_DOCKER_GW,
        "dashboard_port": FL_DASHBOARD_PORT,
        "fl_rounds": os.environ.get("FL_ROUNDS", "2"),
    }


def read_global_config(session):
    """Defaults <- file <- session (most specific wins)."""
    cfg = default_global_config()
    try:
        with open(LAB_CONFIG_PATH, "r") as fh:
            data = json.loads(fh.read())
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in GLOBAL_PARAM_KEYS or k == "fl_scenario"})
    except (IOError, OSError, ValueError):
        pass
    stored = session.get(SESSION_GLOBAL_KEY)
    if isinstance(stored, dict):
        cfg.update(stored)
    return cfg


def scenario_from_plugin_name(plugin_name):
    if not plugin_name:
        return None
    key = plugin_name.strip().lower()
    if key in PLUGIN_SCENARIO:
        return PLUGIN_SCENARIO[key]
    if "heart" in key:
        return "heart"
    if "pm" in key or "maint" in key or "machine" in key:
        return "pm"
    return None


def scenario_from_csv(csv_file):
    if not csv_file:
        return None
    if "heart_" in csv_file:
        return "heart"
    if "machine_" in csv_file:
        return "pm"
    return None


def csv_path_for_board(board_name, scenario=None):
    scenario = scenario if scenario in FL_SCENARIOS else DEFAULT_SCENARIO
    idx = BOARD_INDEX.get(board_name)
    if not idx:
        return ""
    prefix = FL_SCENARIOS[scenario]["csv_prefix"]
    return "/opt/fl/{0}_{1}.csv".format(prefix, idx)


def spec_from_board(board, index=0, global_cfg=None):
    """Build a client spec dict from a live IoTronic board row."""
    name = board["name"]
    scenario = DEFAULT_SCENARIO
    return {
        "slug": board["uuid"],
        "board_id": board["uuid"],
        "board_name": name,
        "board_name_param": name,
        "plugin_name": FL_PLUGIN_HEART,
        "csv_file": csv_path_for_board(name, scenario),
        "fl_scenario": scenario,
    }


def stub_params_json(client):
    return json.dumps(
        {"board_name": client["board_name_param"]},
        indent=2,
        sort_keys=True,
    )


def params_json_for_board(session, slug, client, global_cfg, board_status):
    if board_status != "online" or not client.get("csv_file"):
        return stub_params_json(client)
    stored = session.get("fl_params_{0}".format(slug))
    if stored:
        return stored
    return default_params_json(client, global_cfg)


def save_global_config(session, cfg):
    session[SESSION_GLOBAL_KEY] = cfg
    session.modified = True


def default_params(client, global_cfg=None):
    cfg = global_cfg or default_global_config()
    scenario = client.get("fl_scenario") or DEFAULT_SCENARIO
    if scenario not in FL_SCENARIOS:
        scenario = DEFAULT_SCENARIO
    csv_file = client.get("csv_file") or csv_path_for_board(
        client.get("board_name_param", ""), scenario
    )
    return {
        "server_address": "{0}:{1}".format(
            cfg["server_host"], cfg["server_port"]
        ),
        "csv_file": csv_file,
        "board_name": client["board_name_param"],
        "fl_scenario": scenario,
        "dashboard_url": "http://{0}:{1}".format(
            cfg["dashboard_host"], cfg["dashboard_port"]
        ),
    }


def default_params_json(client, global_cfg=None):
    return json.dumps(default_params(client, global_cfg), indent=2, sort_keys=True)


def params_for_plugin_board(plugin_name, board_name, global_cfg=None):
    scenario = scenario_from_plugin_name(plugin_name)
    if not scenario or not board_name:
        return None
    client = {
        "board_name_param": board_name,
        "fl_scenario": scenario,
        "csv_file": csv_path_for_board(board_name, scenario),
    }
    return default_params_json(client, global_cfg)


def merge_params(client, global_cfg, params_json):
    base = default_params(client, global_cfg)
    if params_json and params_json.strip():
        try:
            overrides = json.loads(params_json)
            if isinstance(overrides, dict):
                for key in ("csv_file", "board_name", "fl_scenario"):
                    if key in overrides and overrides[key]:
                        base[key] = overrides[key]
                detected = scenario_from_csv(base.get("csv_file", ""))
                if detected:
                    base["fl_scenario"] = detected
        except (ValueError, TypeError):
            pass
    return base


def scenario_label(scenario_id):
    meta = FL_SCENARIOS.get(scenario_id) or FL_SCENARIOS[DEFAULT_SCENARIO]
    return meta.get("label", scenario_id)


def lab_plugins_ready(plugins_by_name):
    return all(name in plugins_by_name for name in FL_LAB_PLUGIN_NAMES)
