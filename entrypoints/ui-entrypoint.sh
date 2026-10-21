#!/bin/bash
# Enable FL live dashboard reverse proxy then start Apache (lab overlay).
set -e
a2enmod proxy proxy_http headers 2>/dev/null || true
if [ -f /etc/apache2/conf-available/fl-live-proxy.conf ]; then
  ln -sf /etc/apache2/conf-available/fl-live-proxy.conf /etc/apache2/conf-enabled/fl-live-proxy.conf
fi
if [ -f /etc/apache2/conf-available/metrics-live-proxy.conf ]; then
  ln -sf /etc/apache2/conf-available/metrics-live-proxy.conf /etc/apache2/conf-enabled/metrics-live-proxy.conf
fi
# WoT demos use direct published WSTUN host:port URLs (same host as Horizon).
rm -f /etc/apache2/conf-enabled/00-wot-ws-proxy.conf /etc/apache2/conf-enabled/wot-ws-proxy.conf 2>/dev/null || true
# Upstream fleet_create omitted "return"; Create Fleet then hits fleet.uuid on None.
IOT_API=/usr/share/openstack-dashboard/openstack_dashboard/api/iotronic.py
if [ -f "$IOT_API" ] && grep -q 'iotronicclient(request).fleet.create(\*\*params)' "$IOT_API" \
  && ! grep -q 'return iotronicclient(request).fleet.create(\*\*params)' "$IOT_API"; then
  sed -i 's/^    iotronicclient(request).fleet.create(\*\*params)/    return iotronicclient(request).fleet.create(**params)/' "$IOT_API" || true
fi
exec apache2ctl -D FOREGROUND
