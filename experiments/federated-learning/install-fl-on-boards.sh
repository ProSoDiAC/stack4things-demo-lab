#!/usr/bin/env bash
# Install FL Python deps + datasets for board-alpha/beta/gamma.
#
# Datasets live on the host (experiments/federated-learning/opt-fl) and are
# bind-mounted read-only at /opt/fl on lightning-rod{,-2,-3}.
# Pip packages go into the shared Docker volume lr_fl_python (/opt/fl-python)
# so a Lightning-Rod recreate keeps flwr/torch available (entrypoint writes a .pth).
#
# Installs one board at a time to avoid OOM on small VMs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CH19="${ROOT}/vendor/ch19"
OPT_FL="${ROOT}/experiments/federated-learning/opt-fl"
PIP_OPTS="--no-cache-dir -q"
GEN="${ROOT}/experiments/federated-learning/generate_pm_datasets.py"
FL_TARGET="/opt/fl-python"
# Pin to versions known-good on lrod:compose (Python 3.7)
FL_PKGS=(pandas==1.3.5 scikit-learn==1.0.2 flwr==1.5.0)
TORCH_SPEC="torch==1.13.1+cpu"
TORCH_INDEX="https://download.pytorch.org/whl/cpu"
BOARDS=(lightning-rod lightning-rod-2 lightning-rod-3)

sync_opt_fl_host() {
  mkdir -p "$OPT_FL"
  if [[ ! -f "${CH19}/machine_1.csv" ]]; then
    echo "Generating machine_*.csv datasets..."
    python3 "$GEN" --out "$CH19"
  fi
  for f in machine_1.csv machine_2.csv machine_3.csv heart_1.csv heart_2.csv heart_3.csv data_test_heart.csv data_test_pm.csv; do
    if [[ -f "${CH19}/${f}" ]]; then
      cp -f "${CH19}/${f}" "${OPT_FL}/${f}"
    fi
  done
  cp -f "${ROOT}/experiments/federated-learning/fl_client_plugin.py" "${OPT_FL}/fl_client_plugin.py"
  echo "OK host ${OPT_FL} — $(ls -1 "$OPT_FL" | wc -l) files"
}

ensure_pth() {
  local c="$1"
  docker exec "$c" sh -c \
    'for d in /usr/local/lib/python3*/site-packages; do echo /opt/fl-python > "$d/z_fl_lab.pth"; done'
}

fl_imports_ok() {
  local c="$1"
  docker exec "$c" python3 -c "import flwr, torch, pandas, sklearn" 2>/dev/null
}

install_board() {
  local c="$1"
  if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
    echo "SKIP $c — not running"
    return 0
  fi
  echo "=== $c ==="

  if ! docker exec "$c" test -d /opt/fl; then
    echo "WARN $c — /opt/fl missing (compose mount?). Falling back to docker cp."
    docker exec "$c" mkdir -p /opt/fl
    for f in machine_1.csv machine_2.csv machine_3.csv heart_1.csv heart_2.csv heart_3.csv data_test_heart.csv data_test_pm.csv fl_client_plugin.py; do
      [[ -f "${OPT_FL}/${f}" ]] && docker cp "${OPT_FL}/${f}" "$c:/opt/fl/${f}"
    done
  else
    docker exec "$c" sh -c 'ls /opt/fl/heart_1.csv /opt/fl/machine_1.csv >/dev/null'
    echo "OK $c — /opt/fl mounted"
  fi

  if ! docker exec "$c" test -d "$FL_TARGET"; then
    echo "WARN $c — ${FL_TARGET} missing; creating (volume may be absent)"
    docker exec "$c" mkdir -p "$FL_TARGET"
  fi

  ensure_pth "$c"

  if fl_imports_ok "$c"; then
    echo "OK $c — deps already present via ${FL_TARGET} or site-packages"
  else
    echo "Installing Python deps into ${FL_TARGET} on $c ..."
    docker exec "$c" pip install ${PIP_OPTS} --upgrade-strategy only-if-needed \
      --target="$FL_TARGET" "${FL_PKGS[@]}"
    docker exec "$c" pip install ${PIP_OPTS} --upgrade-strategy only-if-needed \
      --target="$FL_TARGET" "$TORCH_SPEC" --index-url "$TORCH_INDEX" \
      || docker exec "$c" pip3 install ${PIP_OPTS} --upgrade-strategy only-if-needed \
        --target="$FL_TARGET" "$TORCH_SPEC" --index-url "$TORCH_INDEX"
    ensure_pth "$c"
  fi

  docker exec "$c" python3 -c "import flwr, torch; print('flwr', flwr.__version__, 'torch', torch.__version__)"
  echo "OK $c — FL ready"
}

sync_opt_fl_host

for c in "${BOARDS[@]}"; do
  install_board "$c"
  sleep 2
done

echo ""
echo "Lab examples (same fl-client plugin, different local CSV):"
echo "  Heart Ch.19:  csv_file=/opt/fl/heart_N.csv"
echo "  Pred. maint.:  csv_file=/opt/fl/machine_N.csv"
echo ""
echo "  board-alpha: heart_1 or machine_1  |  board-beta: heart_2 or machine_2  |  board-gamma: heart_3 or machine_3"
echo ""
echo "FL packages persist in Docker volume lr_fl_python (/opt/fl-python)."
echo "FL live dashboard: http://<VM_IP>/horizon/fl-live/"
