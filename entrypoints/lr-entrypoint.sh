#!/bin/bash
# Lightning-Rod entrypoint for the lab (replaces the inline `sed ... && exec startLR`); mounted at /opt/s4t-lab.
#  - point the LR at the in-network WSTUN server
#  - make the shared pip target (/opt/fl-python) importable
#  - start optional background helpers (sshd, demo web services)
#  - hand over to the stock startLR (nginx + lightning-rod)
set -u

sed -i 's|self\.wstun_ip *= .*|self.wstun_ip = "iotronic-wstun"|' \
  /usr/local/lib/python3*/site-packages/iotronic_lightningrod/modules/service_manager.py

mkdir -p /opt/fl-python
for d in /usr/local/lib/python3*/site-packages; do
  echo /opt/fl-python > "$d/z_fl_lab.pth"
done

if [ "${LAB_SSHD:-1}" = "1" ] || [ "${LAB_DEMO_SERVICES:-0}" = "1" ]; then
  /opt/s4t-lab/lr-helpers.sh >/var/log/lab-helpers.log 2>&1 &
fi

exec startLR
