#!/usr/bin/env bash
# Lab ops — shared defaults for Stack4Things lab demo scripts.
# Override any variable before calling the scripts, e.g.:
#   BOARD_NAME=demo-edge HOST_PORT=1482 ./01-run-manual-lr.sh

LAB_OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRAINING_ROOT="$(cd "$LAB_OPS_DIR/.." && pwd)"

# Lab host IP for Horizon URLs printed to the operator
if [[ -z "${S4T_LAB_HOST:-}" && -f "$TRAINING_ROOT/vm-ip.txt" ]]; then
  S4T_LAB_HOST="$(tr -d '[:space:]' < "$TRAINING_ROOT/vm-ip.txt")"
fi
export S4T_LAB_HOST="${S4T_LAB_HOST:-127.0.0.1}"

export DOCKER_NETWORK="${DOCKER_NETWORK:-${COMPOSE_PROJECT_NAME:-s4t}_s4t}"
export LR_IMAGE="${LR_IMAGE:-${IMG_LR:-docker.io/mdslab/lrod:compose}}"
export LR_WAMP_URL="${LR_WAMP_URL:-wss://crossbar:8181}"
export LR_UI_USER="${LR_UI_USER:-me}"
export LR_UI_PASS="${LR_UI_PASS:-arancino}"
export HORIZON_USER="${HORIZON_USER:-admin}"
export HORIZON_PASS="${HORIZON_PASS:-s4t}"

export TRAINING_ROOT
export LAB_OPS_DIR
export METRICS_SDK_HOST="${METRICS_SDK_HOST:-$TRAINING_ROOT/experiments/metrics/s4t_metrics.py}"
export OPT_FL_HOST="${OPT_FL_HOST:-$TRAINING_ROOT/experiments/federated-learning/opt-fl}"
export FL_PYTHON_VOL="${FL_PYTHON_VOL:-${COMPOSE_PROJECT_NAME:-s4t}_lr_fl_python}"
