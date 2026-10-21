"""FedAvg strategy that publishes round lifecycle events for the FL dashboard."""
from __future__ import annotations

from collections.abc import Callable

import flwr as fl
from flwr.common import GetPropertiesIns, MetricsAggregationFn, Parameters, Scalar, ndarrays_to_parameters
from flwr.server.client_manager import ClientManager
from flwr.server.client_proxy import ClientProxy
from flwr.server.strategy import FedAvg

from fl_events import _normalize_client, emit


def _resolve_board(client: ClientProxy) -> str:
    """Map Flower client id to IoTronic board name (board-alpha, …)."""
    try:
        res = client.get_properties(
            GetPropertiesIns(config={}),
            timeout=10,
            group_id=None,
        )
        props = getattr(res, "properties", None) or {}
        board = props.get("board_name") or props.get("board")
        if board:
            return _normalize_client(str(board))
    except Exception:
        pass
    return _normalize_client(str(client.cid))


class VisualFedAvg(FedAvg):
    """Instrumented FedAvg — emits events consumed by the S4T FL dashboard."""

    def configure_fit(
        self, server_round: int, parameters: Parameters, client_manager: ClientManager
    ) -> list[tuple[ClientProxy, fl.common.FitIns]]:
        emit(
            "broadcast",
            f"Round {server_round}: broadcasting global weights to edge clients",
            phase="broadcast",
            round=server_round,
        )
        pairs = super().configure_fit(server_round, parameters, client_manager)
        for client, _ in pairs:
            board = _resolve_board(client)
            emit(
                "client_selected",
                f"{board} selected for round {server_round}",
                client=board,
                client_status="connected",
                round=server_round,
                phase="local_training",
            )
        return pairs

    def aggregate_fit(
        self,
        server_round: int,
        results: list[tuple[ClientProxy, fl.common.FitRes]],
        failures: list[tuple[ClientProxy, fl.common.FitRes] | BaseException],
    ) -> tuple[Parameters | None, dict[str, Scalar]]:
        emit(
            "aggregating",
            f"Round {server_round}: FedAvg aggregation on cloud server",
            phase="aggregating",
            round=server_round,
        )
        for client, fit_res in results:
            board = _resolve_board(client)
            emit(
                "weights_received",
                f"Weights received from {board} ({fit_res.num_examples} samples)",
                client=board,
                client_status="uploaded",
                samples=fit_res.num_examples,
                round=server_round,
                phase="upload_weights",
            )
        aggregated = super().aggregate_fit(server_round, results, failures)
        emit(
            "round_complete",
            f"Round {server_round} aggregation complete",
            phase="round_complete",
            round=server_round,
        )
        return aggregated
