#!/usr/bin/env bash
# Lab ops — create IoTronic board + Lightning-Rod container (NO auto-register).
# You register manually in the LR dashboard (first-boot Config page).
#
# Important about ports:
#   Inside EVERY LR container the UI listens on 1474.
#   On the HOST each board has a DIFFERENT published port mapped to that 1474:
#     board-alpha  -> http://<host>:1474/   (container lightning-rod)
#     board-beta   -> http://<host>:1475/   (lightning-rod-2)
#     ...
#     manual board -> http://<host>:HOST_PORT/  (this script, default from 1482)
#
# Examples:
#   ./01-run-manual-lr.sh
#   BOARD_NAME=lab-edge-1 HOST_PORT=1482 ./01-run-manual-lr.sh
#   CREATE_BOARD=0 BOARD_NAME=my-board HOST_PORT=1485 ./01-run-manual-lr.sh
#
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "$DIR/env.sh"

BOARD_NAME="${BOARD_NAME:-board-lab-$(date +%H%M%S)}"
CONTAINER_NAME="${CONTAINER_NAME:-lightning-rod-${BOARD_NAME}}"
CONTAINER_NAME="$(echo "$CONTAINER_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_.-]/-/g')"
HOST_PORT="${HOST_PORT:-}"
CREATE_BOARD="${CREATE_BOARD:-1}"
REG_CODE="${REG_CODE:-}"
WITH_FL="${WITH_FL:-0}"
WITH_METRICS="${WITH_METRICS:-1}"

pick_free_port() {
  local p="${1:-1482}"
  local used
  used="$(docker ps --format '{{.Ports}}' | grep -oE '0\.0\.0\.0:[0-9]+' | cut -d: -f2 | sort -n | uniq || true)"
  while echo "$used" | grep -qx "$p"; do
    p=$((p + 1))
  done
  echo "$p"
}

if [[ -z "$HOST_PORT" ]]; then
  HOST_PORT="$(pick_free_port 1482)"
fi

echo "=== Lab ops create board + LR (manual registration) ==="
echo "board     : $BOARD_NAME"
echo "container : $CONTAINER_NAME"
echo "host UI   : http://${S4T_LAB_HOST}:${HOST_PORT}/   <-- use THIS URL (maps to container :1474)"
echo "network   : $DOCKER_NETWORK"
echo "WAMP hint : $LR_WAMP_URL"
echo "create IoTronic board: $CREATE_BOARD"
echo
echo "NOTE: all LR containers listen on 1474 INTERNALLY;"
echo "      from the browser you must use the host port above, not always :1474."
echo

if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "ERROR: container '$CONTAINER_NAME' already exists."
  echo "Remove it with: ./02-destroy-manual-lr.sh $CONTAINER_NAME"
  echo "List dashboards: ./04-list-lr-dashboards.sh"
  exit 1
fi

if [[ "$CREATE_BOARD" == "1" ]]; then
  if [[ -z "$REG_CODE" ]]; then
    REG_CODE="${BOARD_NAME}-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
  fi
  echo "-> Creating IoTronic board '$BOARD_NAME' ..."
  docker exec -i iotronic-ui python2.7 - "$BOARD_NAME" "$REG_CODE" <<'PY'
import json, sys, urllib2
name, code = sys.argv[1], sys.argv[2]
body = json.dumps({
  "auth": {"identity": {"methods": ["password"], "password": {"user": {
    "name": "admin", "domain": {"name": "Default"}, "password": "s4t"}}},
    "scope": {"project": {"name": "admin", "domain": {"name": "Default"}}}}
})
r = urllib2.urlopen(urllib2.Request(
  "http://keystone:5000/v3/auth/tokens", body,
  {"Content-Type": "application/json"}))
token = r.info().get("X-Subject-Token")
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint="http://iotronic-conductor:8812/v1/")
# refuse duplicate names
for b in c.board.list():
  if b.name == name:
    print(json.dumps({"ok": False, "error": "board name already exists"}))
    raise SystemExit(1)
location = [{"latitude": "38.1938", "longitude": "15.5540", "altitude": "0"}]
try:
  c.board.create(code=code, mobile=False, location=location, type="virtual", name=name)
except Exception:
  c.board.create(code=code, mobile=False, location=location, type="server", name=name)
print(json.dumps({"ok": True, "name": name, "code": code}))
PY
  echo "   registration code: $REG_CODE"
else
  echo "-> Skipping IoTronic board create (CREATE_BOARD=0)"
  if [[ -z "$REG_CODE" ]]; then
    echo "   (no REG_CODE set — enter the code yourself in the LR Config page)"
  else
    echo "   registration code to use: $REG_CODE"
  fi
fi

echo "-> Creating volumes ..."
for s in var le nginx confs data; do
  docker volume create "${CONTAINER_NAME}_${s}" >/dev/null
done

VOL_ARGS=(
  -v "${CONTAINER_NAME}_var:/var/lib/iotronic"
  -v "${CONTAINER_NAME}_le:/etc/letsencrypt"
  -v "${CONTAINER_NAME}_nginx:/etc/nginx"
  -v "${CONTAINER_NAME}_confs:/etc/iotronic"
  -v /var/run/docker.sock:/var/run/docker.sock
  -v "${CONTAINER_NAME}_data:/opt/data"
)

if [[ "$WITH_METRICS" == "1" && -f "$METRICS_SDK_HOST" ]]; then
  VOL_ARGS+=(-v "${METRICS_SDK_HOST}:/opt/lab/s4t_metrics.py:ro")
fi
if [[ "$WITH_FL" == "1" ]]; then
  VOL_ARGS+=(-v "${OPT_FL_HOST}:/opt/fl:ro")
  if docker volume inspect "$FL_PYTHON_VOL" >/dev/null 2>&1; then
    VOL_ARGS+=(-v "${FL_PYTHON_VOL}:/opt/fl-python")
  fi
fi

# Same entrypoint as the compose-managed Lightning-Rods (wstun host fix + shared pip target).
# sshd is installed by this script itself further down, so the helper is disabled here.
VOL_ARGS+=(-v "${TRAINING_ROOT}/entrypoints:/opt/s4t-lab:ro" -e LAB_SSHD=0)

echo "-> docker run $CONTAINER_NAME  (-p ${HOST_PORT}:1474) ..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --privileged \
  --network "$DOCKER_NETWORK" \
  -p "${HOST_PORT}:1474" \
  -l "s4t.lab.dynamic_lr=1" \
  -l "s4t.lab.host_port=${HOST_PORT}" \
  -l "s4t.lab.board_name=${BOARD_NAME}" \
  "${VOL_ARGS[@]}" \
  --entrypoint /bin/bash \
  "$LR_IMAGE" \
  /opt/s4t-lab/lr-entrypoint.sh

echo "-> Waiting for LR dashboard (host :$HOST_PORT -> container :1474) ..."
ok=0
for i in $(seq 1 45); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 "http://127.0.0.1:${HOST_PORT}/" || true)"
  if [[ "$code" =~ ^(200|302|401|403)$ ]]; then
    ok=1
    break
  fi
  sleep 2
done
if [[ "$ok" != "1" ]]; then
  echo "WARN: LR UI not ready yet (HTTP $code). Check: docker logs -f $CONTAINER_NAME"
else
  echo "   LR dashboard is up."
fi

ROOT_PASS="${ROOT_PASS:-arancino}"
echo "-> Installing OpenSSH server inside container (no host port publish) ..."
docker exec "$CONTAINER_NAME" bash -lc "
set -e
if ! command -v sshd >/dev/null 2>&1; then
  if ! apt-get update -qq 2>/dev/null; then
    cat >/etc/apt/sources.list <<EOF
deb http://archive.debian.org/debian buster main
deb http://archive.debian.org/debian-security buster/updates main
deb http://archive.debian.org/debian buster-updates main
EOF
    echo 'Acquire::Check-Valid-Until \"false\";' >/etc/apt/apt.conf.d/99no-check-valid
    apt-get update -qq
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server
fi
mkdir -p /var/run/sshd
ssh-keygen -A >/dev/null 2>&1 || true
echo \"root:${ROOT_PASS}\" | chpasswd
sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\\?UsePAM.*/UsePAM no/' /etc/ssh/sshd_config
pkill -x sshd 2>/dev/null || true
/usr/sbin/sshd
cat >/usr/local/bin/start-sshd-lab.sh <<'EOF'
#!/bin/sh
mkdir -p /var/run/sshd
ssh-keygen -A >/dev/null 2>&1 || true
pgrep -x sshd >/dev/null || /usr/sbin/sshd
EOF
chmod +x /usr/local/bin/start-sshd-lab.sh
pgrep -x sshd >/dev/null
" || echo "WARN: SSH install failed (check docker logs / apt mirrors)"

IP="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_NAME")"

echo
echo "========== CREATED (not registered yet) =========="
echo "Board name      : $BOARD_NAME"
echo "Reg. code       : ${REG_CODE:-(set by you / already known)}"
echo "Container       : $CONTAINER_NAME"
echo "Docker IP       : $IP   (rete $DOCKER_NETWORK)"
echo
echo "SSH (solo nel container — nessuna porta SSH pubblicata sull'host):"
echo "  user/pass : root / ${ROOT_PASS}"
echo "  dalla lab host: ssh root@${IP}"
echo "  oppure: docker exec -it ${CONTAINER_NAME} bash"
echo
echo "LR DASHBOARD (open this in the browser):"
echo "  http://${S4T_LAB_HOST}:${HOST_PORT}/"
echo "  login after registration: ${LR_UI_USER} / ${LR_UI_PASS}"
echo
echo "Manual registration (first-boot Config page):"
echo "  1) Open the URL above"
echo "  2) WAMP / urlwagent = ${LR_WAMP_URL}"
echo "  3) Code             = ${REG_CODE:-(registration code of the IoTronic board)}"
echo "  4) Hostname         = ${BOARD_NAME}"
echo "  5) CONFIGURE — then board becomes online in Horizon"
echo
echo "Port reminder:"
echo "  container internal UI port = always 1474"
echo "  YOUR host port for THIS board = ${HOST_PORT}"
echo "  (board-alpha is :1474, beta :1475, ... — see ./04-list-lr-dashboards.sh)"
echo
echo "Horizon: http://${S4T_LAB_HOST}/horizon/  (${HORIZON_USER}/${HORIZON_PASS})"
echo "Destroy: ./02-destroy-manual-lr.sh $CONTAINER_NAME [--delete-board]"
echo "=================================================="

STATE_FILE="$DIR/.last-manual-lr.env"
if ! cat > "$STATE_FILE" <<EOF
BOARD_NAME=$BOARD_NAME
CONTAINER_NAME=$CONTAINER_NAME
HOST_PORT=$HOST_PORT
REG_CODE=${REG_CODE:-}
DOCKER_IP=$IP
ROOT_PASS=$ROOT_PASS
EOF
then
  ALT="/tmp/lab-ops-last-manual-lr.env"
  cat > "$ALT" <<EOF
BOARD_NAME=$BOARD_NAME
CONTAINER_NAME=$CONTAINER_NAME
HOST_PORT=$HOST_PORT
REG_CODE=${REG_CODE:-}
DOCKER_IP=$IP
EOF
  echo "WARN: could not write $STATE_FILE; saved $ALT instead"
fi
