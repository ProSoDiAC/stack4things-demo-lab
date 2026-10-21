# Architecture

## Services

```
                         browser ──► :80  iotronic-ui (Horizon + lab panels, Apache)
                                         │  /horizon/fl-live/ ─► fl-control:8090      (reverse proxies, same origin)
                                         │  /horizon/metrics-live/ ─► grafana:3000
                                         ▼
 keystone:5000 ◄── auth ── iotronic-conductor:8812 (REST + RPC) ──► iotronic-db (MariaDB)
                                   │  RabbitMQ (RPC)
                                   ▼
                          iotronic-wagent ──► crossbar:8181 (WAMP/TLS, realm "s4t") ◄── Lightning-Rod ×6 (+ dynamic ones)
                                                                                         │  wss://crossbar:8181
 iotronic-wstun:8080 + 50001-50100 ◄── reverse tunnels (services exposed by boards) ─────┘

 metrics:  EnvironmentalDemo ─► metrics-gateway:8093 ─► influxdb:8086 ─► grafana:3000
 FL:       fl-client-* plugins ─► fl-control (Flower server :8087, dashboard :8090, control API :8091)
 helper:   lr-log-proxy:8092  (LR logs for Horizon, create/delete Lightning-Rod containers via the Docker socket)
 PKI:      ca_service generates a root CA + Crossbar certificate into the shared volume (once)
```

| Container | Image | Role |
|---|---|---|
| `ca_service` | alpine | one-shot PKI (replaces upstream `debian:buster`, whose apt repositories no longer exist) |
| `crossbar` | `crossbario/crossbar` | WAMP router; config in `conf/crossbar/config.json` |
| `iotronic-wstun` | `mdslab/iotronic-wstun` | WebSocket tunnel server; the public ports 50001-50100 are the exposed board services |
| `iotronic-db` | `mariadb` | `iotronic` and `keystone` databases |
| `rabbitmq` | `rabbitmq:3.7-management` | conductor ⇄ agent RPC |
| `keystone` | `mdslab/iotronic-keystone` | identity; the `iot` service, roles and endpoints are created idempotently at start |
| `iotronic-conductor` | `mdslab/iotronic-conductor` | IoTronic REST API + RPC server (with the lab bug-fix patch) |
| `iotronic-wagent` | `mdslab/iotronic-wagent` | WAMP agent bridging boards and the conductor |
| `iotronic-ui` | `mdslab/iotronic-ui` | Horizon dashboard plus the lab panels (see *Patches*) |
| `lightning-rod` … `-6` | `mdslab/lrod` | six virtual boards (alpha … zeta). Alpha also hosts the weather API and the WoT demo |
| `influxdb`, `grafana` | upstream | metrics storage and dashboards (provisioned from `patches/grafana/`) |
| `metrics-gateway` | built from `docker/metrics-gateway` | token-based write API in front of InfluxDB + stream registry |
| `fl-control` | built from `docker/fl-control` | Flower server, live dashboard and control API (CPU-only PyTorch) |
| `lr-log-proxy` | built from `docker/lr-log-proxy` | Docker-socket helper for Horizon (logs, dynamic Lightning-Rods) |

All upstream images are pinned **by digest** in `.env.example` (`IMG_*`), so the lab is reproducible even though
the upstream tags (`latest`) move. The three local images pin their Python dependencies.

## Network

A single bridge network `<project>_s4t` with a fixed subnet (`S4T_SUBNET`, default `10.250.0.0/24`). Services find each
other by container name (`keystone`, `crossbar`, `fl-control`, ...). Nothing in the lab depends on the host's
Docker bridge address: the Flower server is reached as `fl-control:8087`, Grafana as `grafana:3000`, and so on.

Published ports are split in two groups (`.env`: `BIND_PUBLIC`, `BIND_INTERNAL`):

| Group | Default bind | Ports |
|---|---|---|
| public | `0.0.0.0` | 80 Horizon · 3000 Grafana · 8181 Crossbar · 8080 WSTUN · 50001-50100 WSTUN services · 1474-1479 Lightning-Rod UIs (+1480… for on-demand boards) |
| internal | `127.0.0.1` | 3306 MariaDB · 5000 Keystone · 8812 Conductor · 5672/15672 RabbitMQ · 8086 InfluxDB · 8090/8091 FL · 8092 LR proxy · 8093 metrics gateway |

External physical boards only need 8181 (WAMP), 8080 and 50001-50100 (WSTUN); on those devices `crossbar` and
`iotronic-wstun` must resolve to the lab host (an `/etc/hosts` entry is enough).

## State and persistence

Every piece of state is in a named volume:

| Volume (prefix `<project>_`) | Holds |
|---|---|
| `unime_iotronic_db_data` | MariaDB: boards, plugins, services, fleets, users, projects |
| `iotronic_ssl`, `crossbar_data` | root CA, Crossbar certificate and node key |
| `keystone_fernet`, `keystone_credentials` | Keystone token and credential encryption keys |
| `rabbitmq_data` | RabbitMQ |
| `lr_*`, `lr2_*` … `lr6_*` (`_var _le _nginx _confs _data`) | per-board Lightning-Rod identity, installed plugins, exposed services, nginx config, datasets |
| `lr_fl_python` | Python packages for the FL clients (shared by all boards, installed once) |
| `influxdb_data`, `grafana_data`, `metrics_streams` | metrics, Grafana state, stream registry |
| `iotronic_logs`, `iotronic-ui_logs`, `keystone_*logs` | logs |

What makes a restart / reboot / `--force-recreate` come back to a working state without manual steps:

* **Stable identities.** The conductor and the agent register in the database *by hostname*; Compose pins them
  (`iotronic-conductor`, `iotronic-wagent`). With container-id hostnames every re-creation would orphan the boards'
  agent binding.
* **Keystone** keeps its Fernet keys in volumes and runs Apache as its main process (so a crash restarts the
  container); its bootstrap (`entrypoints/keystone-entrypoint.sh`) is idempotent and the health check requires both
  the setup marker and a live `/v3` endpoint.
* **Ordering** is expressed with health checks (`depends_on: condition: service_healthy`) and each entrypoint
  waits for what it needs, so the "everything starts at once after a reboot" case works too.
* **Lightning-Rods** restore their exposed WSTUN services and injected plugins from their volumes. The lab entrypoint
  (`entrypoints/lr-entrypoint.sh`) additionally restarts the demo processes that used to be started by hand
  (weather API, WoT API + nginx site, sshd) and re-links the shared Python packages.
* **`EnvironmentalDemo`** is injected with `onboot=true` after its first start, so the LR restarts it with the saved
  metrics parameters; the plugin also replays the dataset in a loop instead of stopping when it is exhausted.
* **`fl-control`** starts the Flower server and dashboard on boot (`FL_AUTOSTART`, default on).
* **Disposable containers.** Helper images are built, not `pip install`-ed at start, so a recreate needs no internet.
  (sshd is the exception: it is installed with apt on first start of each Lightning-Rod container and cached in the
  container layer.)

## Patches over the upstream images

Nothing is rebuilt; the lab overlays files by bind mount (see `docker-compose.yml`):

| Patch | Why |
|---|---|
| `patches/iotronic_conductor_endpoints.py` | upstream `except exception:` (lower-case) is a `NameError` on Python 3: deleting an online board failed |
| `patches/iotronic_ui_lab/` (Horizon panels: Federated Learning, IoT Metrics, WoT, LR logs) | lab-specific dashboards, enabled through `patches/horizon-enabled/` |
| `patches/iotronic_ui_fleets_lab/`, `…_boards_lab/`, `…_plugins_lab/` | fleet operations (inject / call / remove on a fleet, create-fleet fix), *Create LR container* button, Boards log tab, Plugin IDE |
| `patches/iotronic_ui_dashboard_lab.py`, `…_webservices_panel_stub.py`, `horizon-enabled/_6040_*` | sidebar organisation; the upstream *Web services* panel is hidden in favour of *Services* + *WoT* |
| `patches/horizon-local-settings-en.py`, `lab_force_en.py` | force the English UI |
| `patches/apache-*-proxy.conf` | same-origin reverse proxies for the FL dashboard and Grafana iframes |
| `patches/grafana/` | provisioned data source and the *S4T IoT Metrics* dashboard |
| `entrypoints/ui-entrypoint.sh` | enables the proxies; fixes upstream `fleet_create` missing a `return` |
