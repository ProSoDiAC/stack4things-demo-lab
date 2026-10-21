#!/bin/bash
# Background helpers started by lr-entrypoint.sh (all idempotent, best-effort):
#   LAB_SSHD=1           sshd on :22 (exposed through WSTUN by the "ssh-remote" service)
#   LAB_DEMO_SERVICES=1  weather API (:8088) and WoT Fritzing UI/API (nginx :8090, API :8091)
set -u
log() { echo "[lr-helpers] $*"; }

if [ "${LAB_SSHD:-1}" = "1" ]; then
  if ! command -v sshd >/dev/null 2>&1; then
    log "installing openssh-server (debian buster is EOL -> archive.debian.org)"
    cat > /etc/apt/sources.list <<APT
deb http://archive.debian.org/debian buster main contrib non-free
deb http://archive.debian.org/debian-security buster/updates main contrib non-free
APT
    apt-get -o Acquire::Check-Valid-Until=false update -qq && apt-get install -y -qq openssh-server
  fi
  if command -v sshd >/dev/null 2>&1; then
    echo "root:${LAB_SSH_PASSWORD:-arancino}" | chpasswd
    mkdir -p /run/sshd
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/; s/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
    grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
    grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
    ssh-keygen -A >/dev/null 2>&1
    pgrep -x sshd >/dev/null || /usr/sbin/sshd
    log "sshd running"
  else
    log "WARN sshd not available"
  fi
fi

if [ "${LAB_DEMO_SERVICES:-0}" = "1" ]; then
  # startLR launches nginx; wait for it so we can reload with the extra site.
  for _ in $(seq 1 60); do pgrep -x nginx >/dev/null && break; sleep 1; done
  DEMO=/opt/s4t-demo

  pgrep -f weather_web_server.py >/dev/null || \
    nohup python3 "$DEMO/weather_web_server.py" 8088 >/tmp/weather.log 2>&1 &

  mkdir -p /var/www/wot-fritzing /etc/nginx/sites-available /etc/nginx/sites-enabled
  cp "$DEMO/wot-fritzing/www/index.html" /var/www/wot-fritzing/index.html
  cp "$DEMO/wot-fritzing/nginx-wot-fritzing.conf" /etc/nginx/sites-available/wot-fritzing
  ln -sf /etc/nginx/sites-available/wot-fritzing /etc/nginx/sites-enabled/wot-fritzing
  pgrep -f wot_board_api.py >/dev/null || \
    nohup python3 "$DEMO/wot-fritzing/wot_board_api.py" 8091 >/tmp/wot-board-api.log 2>&1 &
  nginx -t >/dev/null 2>&1 && nginx -s reload
  log "demo services started"
fi
