# =============================================================================
# Federated Learning client plugin (Flower + PyTorch) - Stack4Things Ch.19 lab
# =============================================================================
#
# WHAT & WHY
# ---------
# This async Lightning-Rod plugin runs a Flower (flwr) edge client on a board.
# It trains a small neural network on LOCAL telemetry (predictive maintenance CSV),
# then sends weight updates to the central Flower server on the cloud VM. The server
# aggregates updates with FedAvg; no raw sensor data leaves the board.
#
# One async plugin source on cloud; register two names in Horizon:
#   fl-client-heart  -> heart_*.csv (clinical cohorts)
#   fl-client-pm     -> machine_*.csv (predictive maintenance lab)
# Pick the plugin per board in the Cloud plugin dropdown; JSON csv_file follows.
#
# HOW TO USE (Horizon -> IoT -> Federated Learning)
# ------------------------------------------------
# 1. Create / update FL client plugins (heart + PM).
# 2. Map each board to fl-client-heart OR fl-client-pm and inject.
# 3. Per-board Start parameters (JSON) are prefilled from the plugin name.
# 4. Start Flower server, then Start all clients (same plugin on every board).
# 5. Live topology labels follow the active scenario automatically.
#
# START PARAMETERS (JSON) - per-board differentiation
# ---------------------------------------------------
# Pass these keys in the JSON textarea when starting the plugin on each board:
#
#   server_address   Host:port of the Flower gRPC server (cloud VM).
#                    Example: "fl-control:8087"
#   csv_file         Path to the LOCAL training CSV on this board (LR container).
#                    Example: "/opt/fl/machine_1.csv"
#   board_name       Label for live dashboard / logs (match IoTronic board name).
#                    Example: "board-alpha"
#   dashboard_url    HTTP URL of the FL live dashboard (for edge event posts).
#                    Example: "http://fl-control:8090"
#
# CSV schema (predictive maintenance - one file per production line):
#   vibration_rms, vibration_peak, temperature_c, motor_current_a,
#   load_pct, hours_since_service, target (0=healthy, 1=failure imminent)
#
# Global lab settings (rounds, server host, dashboard host) are managed in
# "Lab parameters" in the Horizon panel; server_address and dashboard_url in
# the JSON are filled from those settings when you save or start clients.
#
# Example JSON for board-beta (conveyor motor / machine_2):
#
#   {
#     "board_name": "board-beta",
#     "csv_file": "/opt/fl/machine_2.csv",
#     "dashboard_url": "http://fl-control:8090",
#     "server_address": "fl-control:8087"
#   }
#
# Example JSON for board-gamma (pump line / machine_3):
#
#   {
#     "board_name": "board-gamma",
#     "csv_file": "/opt/fl/machine_3.csv",
#     "dashboard_url": "http://fl-control:8090",
#     "server_address": "fl-control:8087"
#   }
#
# REQUIREMENTS on the edge board (LR container)
# -------------------------------------------
# - Python packages: flwr, torch, pandas, scikit-learn
# - Dataset CSV mounted at csv_file path (install-fl-on-boards.sh for the lab)
#
# =============================================================================

"""Federated Learning Flower client for Lightning-Rod (async plugin)."""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict

import flwr as fl
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from iotronic_lightningrod.modules.plugins import Plugin
from oslo_log import log as logging
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

LOG = logging.getLogger(__name__)

_CLIENT_LOCK = threading.Lock()
_CLIENT_THREADS = {}
_MAX_CONNECT_ATTEMPTS = 60
_RETRY_SLEEP_SEC = 2


def _parse_server_address(server_address: str) -> tuple[str, int]:
    host, _, port = server_address.rpartition(":")
    return (host or "127.0.0.1", int(port or "8087"))


def _flower_server_open(server_address: str, timeout: float = 2.0) -> bool:
    host, port = _parse_server_address(server_address)
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _wait_for_flower_server(server_address: str, max_wait: float = 120.0) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _flower_server_open(server_address):
            return True
        time.sleep(1)
    return False


def _safe_dashboard_text(value) -> str:
    text = str(value)
    return text.encode("ascii", "replace").decode("ascii")


def _dashboard_post(url: str, payload: dict) -> None:
    if not url:
        return
    try:
        data = __import__("json").dumps(payload).encode()
        req = urllib.request.Request(
            url.rstrip("/") + "/api/client-event",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        LOG.debug("Dashboard notify skipped: %s", exc)


class Net(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, 2)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


def _get_weights(model):
    return [val.cpu().numpy() for _, val in model.state_dict().items()]


def _set_weights(model, parameters):
    keys = list(model.state_dict().keys())
    state_dict = OrderedDict({k: torch.tensor(v) for k, v in zip(keys, parameters)})
    model.load_state_dict(state_dict, strict=True)


def _load_data(csv_file: str):
    if not os.path.isfile(csv_file):
        raise FileNotFoundError(f"Dataset not found: {csv_file}")
    df = pd.read_csv(csv_file)
    if "target" not in df.columns:
        raise ValueError("CSV must contain a 'target' column")
    df = df.dropna()
    x = df.drop("target", axis=1).values.astype("float32")
    y = df["target"].values.astype("int64")
    x = StandardScaler().fit_transform(x)
    x = torch.tensor(x)
    y = torch.tensor(y)
    split = int(0.8 * len(x))
    return (x[:split], y[:split]), (x[split:], y[split:]), x.shape[1]


class MaintenanceClient(fl.client.NumPyClient):
    def __init__(self, csv_file: str, board_name: str = "board-alpha", dashboard_url: str = ""):
        (self.x_train, self.y_train), (self.x_test, self.y_test), input_dim = _load_data(csv_file)
        self.model = Net(input_dim)
        self.loss_fn = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        self.board_name = board_name
        self.dashboard_url = dashboard_url
        self.fl_scenario_id = "pm" if "machine_" in csv_file else "heart"
        self.csv_file = csv_file

    def get_parameters(self, config):
        return _get_weights(self.model)

    def fit(self, parameters, config):
        rnd = config.get("round", "?")
        _dashboard_post(
            self.dashboard_url,
            {
                "kind": "local_train",
                "client": self.board_name,
                "message": f"{self.board_name}: local training (round {rnd})",
                "phase": "local_training",
                "client_status": "training",
                "round": rnd,
                "fl_scenario": self.fl_scenario_id,
                "csv_file": self.csv_file,
            },
        )
        _set_weights(self.model, parameters)
        self.model.train()
        loader = DataLoader(TensorDataset(self.x_train, self.y_train), batch_size=16, shuffle=True)
        for x_batch, y_batch in loader:
            self.optimizer.zero_grad()
            out = self.model(x_batch)
            loss = self.loss_fn(out, y_batch)
            loss.backward()
            self.optimizer.step()
        weights = _get_weights(self.model)
        _dashboard_post(
            self.dashboard_url,
            {
                "kind": "upload",
                "client": self.board_name,
                "message": f"{self.board_name}: uploading weight update",
                "phase": "upload_weights",
                "client_status": "uploaded",
                "samples": len(self.x_train),
                "round": rnd,
                "fl_scenario": self.fl_scenario_id,
                "csv_file": self.csv_file,
            },
        )
        return weights, len(self.x_train), {}

    def evaluate(self, parameters, config):
        _set_weights(self.model, parameters)
        self.model.eval()
        with torch.no_grad():
            out = self.model(self.x_test)
            loss = self.loss_fn(out, self.y_test).item()
            acc = (out.argmax(1) == self.y_test).float().mean().item()
        return loss, len(self.x_test), {"accuracy": acc}

    def get_properties(self, config):
        return {
            "board_name": self.board_name,
            "fl_scenario": self.fl_scenario_id,
            "csv_file": self.csv_file,
        }


class Worker(Plugin.Plugin):
    def __init__(self, uuid, name, q_result=None, params=None):
        super().__init__(uuid, name, q_result, params)
        self.server_address = (params or {}).get("server_address", "fl-control:8087")
        self.csv_file = (params or {}).get("csv_file", "/opt/fl/heart_1.csv")
        self.board_name = (params or {}).get("board_name", "board-alpha")
        self.fl_scenario = (params or {}).get("fl_scenario", "heart")
        if "heart_" in self.csv_file:
            self.fl_scenario = "heart"
        elif "machine_" in self.csv_file:
            self.fl_scenario = "pm"
        self.dashboard_url = (params or {}).get(
            "dashboard_url", os.environ.get("FL_DASHBOARD_URL", "http://fl-control:8090")
        )
        self._thread = None
        self._run_id = "{0}-{1}".format(self.board_name, time.time())

    def run(self):
        LOG.info(
            "FL plugin %s v2 starting - server=%s csv=%s board=%s",
            self.name, self.server_address, self.csv_file, self.board_name,
        )
        _dashboard_post(
            self.dashboard_url,
            {
                "kind": "client",
                "client": self.board_name,
                "message": "{0}: waiting for Flower server".format(self.board_name),
                "client_status": "reconnecting",
                "fl_scenario": self.fl_scenario,
                "csv_file": self.csv_file,
            },
        )

        def _client_main():
            attempts = 0
            while attempts < _MAX_CONNECT_ATTEMPTS:
                attempts += 1
                if not _wait_for_flower_server(self.server_address, max_wait=30):
                    LOG.warning(
                        "Flower server %s not reachable (attempt %s/%s)",
                        self.server_address,
                        attempts,
                        _MAX_CONNECT_ATTEMPTS,
                    )
                    _dashboard_post(
                        self.dashboard_url,
                        {
                            "kind": "client",
                            "client": self.board_name,
                            "message": "{0}: waiting for Flower server".format(
                                self.board_name
                            ),
                            "client_status": "reconnecting",
                            "fl_scenario": self.fl_scenario,
                            "csv_file": self.csv_file,
                        },
                    )
                    time.sleep(_RETRY_SLEEP_SEC)
                    continue

                _dashboard_post(
                    self.dashboard_url,
                    {
                        "kind": "connect",
                        "client": self.board_name,
                        "message": "{0}: connecting to Flower server".format(self.board_name),
                        "client_status": "connected",
                        "fl_scenario": self.fl_scenario,
                        "csv_file": self.csv_file,
                    },
                )

                try:
                    fl.client.start_numpy_client(
                        server_address=self.server_address,
                        client=MaintenanceClient(
                            self.csv_file, self.board_name, self.dashboard_url
                        ),
                    )
                    LOG.info("FL client %s finished normally", self.board_name)
                    return
                except Exception as exc:
                    LOG.warning(
                        "Flower client %s failed (attempt %s): %s",
                        self.board_name,
                        attempts,
                        exc,
                    )
                    _dashboard_post(
                        self.dashboard_url,
                        {
                            "kind": "client",
                            "client": self.board_name,
                            "message": "{0}: reconnecting to Flower ({1})".format(
                                self.board_name, _safe_dashboard_text(exc)
                            ),
                            "client_status": "reconnecting",
                            "fl_scenario": self.fl_scenario,
                            "csv_file": self.csv_file,
                        },
                    )
                    time.sleep(_RETRY_SLEEP_SEC)

            msg = "Flower server unavailable at {0}".format(self.server_address)
            LOG.error(msg)
            if self.q_result is not None:
                self.q_result.put(msg)

        with _CLIENT_LOCK:
            prev = _CLIENT_THREADS.get(self.board_name)
            if prev and prev.is_alive():
                LOG.info(
                    "Replacing existing FL client thread on %s", self.board_name
                )
            self._thread = threading.Thread(
                target=_client_main, name="fl-{0}".format(self.board_name), daemon=True
            )
            _CLIENT_THREADS[self.board_name] = self._thread
        self._thread.start()
