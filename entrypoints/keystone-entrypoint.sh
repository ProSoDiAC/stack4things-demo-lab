#!/bin/bash
# Idempotent Keystone bootstrap for the Stack4Things lab.
# Apache (the Keystone API) is the container's main process: if it dies the
# container exits and Docker restarts it (the upstream script left Apache in a
# background subshell, so a restart could leave Keystone down while "healthy").
set -u

DB_HOST="${DB_HOST:-iotronic-db}"
DB_ROOT_PASS="${MYSQL_ROOT_PASSWORD:-unime}"
KS_DB_PASS="${KEYSTONE_DBPASS:-unime}"
ADMIN_PASS="${ADMIN_PASS:-s4t}"
IOTRONIC_PASS="${IOTRONIC_PASS:-unime}"   # must match conf/conductor/iotronic.conf
REGION="${REGION_NAME:-RegionOne}"

log() { echo "[keystone-init] $*"; }

rm -f /tmp/keystone-setup-done /var/run/apache2/apache2.pid

sed -i "s|^connection *=.*|connection = mysql+pymysql://keystone:${KS_DB_PASS}@${DB_HOST}/keystone|" /etc/keystone/keystone.conf
chown -R keystone:keystone /var/log/keystone 2>/dev/null || true
touch /var/log/keystone/keystone-manage.log && chmod 777 /var/log/keystone/keystone-manage.log

log "waiting for database ${DB_HOST}..."
until mysql -h "$DB_HOST" -uroot -p"$DB_ROOT_PASS" -e 'SELECT 1' >/dev/null 2>&1; do sleep 3; done

log "ensuring databases and users"
mysql -h "$DB_HOST" -uroot -p"$DB_ROOT_PASS" <<SQL
CREATE DATABASE IF NOT EXISTS keystone;
CREATE DATABASE IF NOT EXISTS iotronic;
CREATE USER IF NOT EXISTS 'keystone'@'%' IDENTIFIED BY '${KS_DB_PASS}';
CREATE USER IF NOT EXISTS 'iotronic'@'%' IDENTIFIED BY '${IOTRONIC_PASS}';
GRANT ALL PRIVILEGES ON keystone.* TO 'keystone'@'%';
GRANT ALL PRIVILEGES ON iotronic.* TO 'iotronic'@'%';
FLUSH PRIVILEGES;
SQL

mkdir -p /etc/keystone/fernet-keys /etc/keystone/credential-keys
chown -R keystone:keystone /etc/keystone
[ -f /etc/keystone/fernet-keys/0 ] || su -s /bin/sh -c 'keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone' keystone
[ -f /etc/keystone/credential-keys/0 ] || su -s /bin/sh -c 'keystone-manage credential_setup --keystone-user keystone --keystone-group keystone' keystone

log "db_sync + bootstrap"
su -s /bin/sh -c 'keystone-manage db_sync' keystone
su -s /bin/sh -c "keystone-manage bootstrap --bootstrap-password '${ADMIN_PASS}' \
  --bootstrap-admin-url http://keystone:5000/v3 --bootstrap-internal-url http://keystone:5000/v3 \
  --bootstrap-public-url http://keystone:5000/v3 --bootstrap-region-id ${REGION}" keystone

log "starting Apache"
apache2ctl -D FOREGROUND &
APACHE_PID=$!

until curl -sf http://localhost:5000/v3 >/dev/null 2>&1; do
  kill -0 "$APACHE_PID" 2>/dev/null || { log "Apache exited during startup"; exit 1; }
  sleep 2
done

export OS_USERNAME=admin OS_PASSWORD="$ADMIN_PASS" OS_PROJECT_NAME=admin
export OS_USER_DOMAIN_NAME=Default OS_PROJECT_DOMAIN_NAME=Default
export OS_AUTH_URL=http://localhost:5000/v3 OS_IDENTITY_API_VERSION=3

log "ensuring Iotronic project, service, user, roles, endpoints"
openstack project show service >/dev/null 2>&1 || openstack project create --domain default --description "Service Project" service
openstack service list -f value -c Name | grep -qx Iotronic || openstack service create iot --name Iotronic
openstack user show iotronic >/dev/null 2>&1 || openstack user create --password "$IOTRONIC_PASS" iotronic
for r in admin_iot_project manager_iot_project user_iot; do
  openstack role show "$r" >/dev/null 2>&1 || openstack role create "$r"
done
openstack role add --project service --user iotronic admin
openstack role add --project service --user iotronic admin_iot_project
openstack role add --project admin --user admin admin_iot_project
for iface in public internal admin; do
  if [ -z "$(openstack endpoint list --service iot --interface "$iface" -f value -c ID)" ]; then
    openstack endpoint create --region "$REGION" iot "$iface" http://iotronic-conductor:8812
  fi
done

touch /tmp/keystone-setup-done
log "ready"
wait "$APACHE_PID"
