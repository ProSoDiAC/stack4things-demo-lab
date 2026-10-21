#!/bin/bash
chown -R iotronic:iotronic /var/log/iotronic
exec /usr/local/bin/iotronic-wamp-agent --config-file /etc/iotronic/iotronic.conf
