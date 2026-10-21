#!/bin/bash
# Iotronic conductor: wait for the DB, migrate, then run Apache + conductor.
set -u
DB_HOST="${DB_HOST:-iotronic-db}"
until mysql -h "$DB_HOST" -uiotronic -p"${IOTRONIC_DBPASS:-unime}" -e 'SELECT 1' >/dev/null 2>&1; do
  echo "[conductor] waiting for database..."; sleep 3
done
iotronic-dbsync
chown -R iotronic:iotronic /var/log/iotronic
exec /usr/local/bin/startConductor
