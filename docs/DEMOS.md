# Demos

All demos start from a bootstrapped lab (`./lab up && ./lab bootstrap`). Sidebar: **IoT → Boards, Plugins, Services,
Fleets, Web Services, Metrics, Federated Learning**. Replace `<host>` with the address given to `./lab init`.

## 1. Boards and the control plane

* **IoT → Boards**: six virtual boards (`board-alpha` … `board-zeta`), status *online*.
* Each board's Lightning-Rod has its own UI on `http://<host>:1474` (alpha) … `:1479` (zeta), login `me` / `arancino`.
* **Boards → Create LR Container** creates a new board *and* starts a Lightning-Rod container for it (host port ≥ 1480);
  deleting the board removes the container. Check the whole cycle with `python3 tests/dynamic-board.py`.
* The *Logs* tab of a board shows its Lightning-Rod log (served by `lr-log-proxy`).

REST access (loopback):

```bash
TOKEN=$(curl -si http://127.0.0.1:5000/v3/auth/tokens -H 'Content-Type: application/json' -d \
 '{"auth":{"identity":{"methods":["password"],"password":{"user":{"name":"admin","domain":{"name":"Default"},"password":"s4t"}}},
   "scope":{"project":{"name":"admin","domain":{"name":"Default"}}}}}' | tr -d '\r' | awk -F': ' 'tolower($1)=="x-subject-token"{print $2}')
curl -s -H "X-Auth-Token: $TOKEN" http://127.0.0.1:8812/v1/boards/ | python3 -m json.tool
```

## 2. Plugins

* `HelloName` (synchronous): **Plugins → HelloName → inject on a board → Call**, parameters `{"name": "Messina"}` →
  `Hello Messina`.
* `EnvironmentalDemo` (asynchronous): see *Metrics* below.
* **Plugins** also hosts a plugin IDE for writing and updating plugin code from the browser.
* Docker-socket access from plugins works too (every Lightning-Rod mounts `/var/run/docker.sock`): a plugin can run
  containers on the lab host.

## 3. Fleets

**Fleets → Create Fleet**, add boards, then *Inject plugin*, *Call plugin* or *Remove plugin* on the whole fleet.
`python3 experiments/multiboard/verify-fleet-360.py` runs 37 checks over the whole fleet workflow
(create, add/move boards, inject, call, remove, log proxy, UI pages).

## 4. Metrics: board → InfluxDB → Grafana

`EnvironmentalDemo` replays a real environmental time series (≈ 62 000 rows, one row every 30 s, looping) from
`board-alpha` through `metrics-gateway` into InfluxDB (`s4t_iot` / `environmental_data`). It is injected with
*start on boot*, so it resumes by itself after any restart.

* **IoT → Metrics**: stream list and the embedded Grafana dashboard *S4T IoT Metrics*.
* Grafana directly: `http://<host>:3000`.
* Query: `docker exec influxdb influx -username admin -password admin -database s4t_iot -execute 'SELECT * FROM environmental_data ORDER BY time DESC LIMIT 5'`
* Gateway health: `curl http://127.0.0.1:8093/health`; active streams: `curl http://127.0.0.1:8093/v1/streams/active`.
* Any plugin can publish through the SDK mounted at `/opt/lab/s4t_metrics.py` (`MetricsWriter.from_params(params)`).

## 5. Web services over WSTUN (web of things)

Services run inside `board-alpha` and are exposed to the outside through the WSTUN server:

| Service | Local port in the board | What it is |
|---|---|---|
| `weather-wot` | 8088 | weather station thing: `/` UI, `/sensors`, `/led/status`, `/history`, `/opendata` |
| `wot-fritzing` | 8090 | nginx serving a circuit UI + board API (`/api/circuit`, LED control) |
| `lr-nginx-demo` | 50000 | the board's stock nginx |
| `ssh-remote` | 22 | sshd (`root` / `arancino`), exposed on **every** board |

**IoT → Web Services** (and *IoT → Services*) list the services with their public URL
`http://<host>:<public port>/`; the port is assigned by WSTUN (range 50001-50100) and is stable across restarts.
The helper processes are started by the Lightning-Rod entrypoint, so they survive restarts and re-creation.

## 6. Federated learning

A Flower server runs in `fl-control`; the clients are the `fl-client-heart` / `fl-client-pm` plugins on
`board-alpha/beta/gamma`, each with its own dataset slice under `/opt/fl` (heart-disease and predictive-maintenance).

* **IoT → Federated Learning**: choose the scenario and rounds, start the server, start the clients; the live topology
  (also `http://<host>/horizon/fl-live/`) shows rounds, accuracy and per-client state.
* Scripted run (2 rounds per scenario): `bash experiments/federated-learning/test-fl-workflows.sh` (~1 min).
* The Python dependencies for the clients (Flower, PyTorch CPU 1.13, pandas, scikit-learn) live in the shared
  `lr_fl_python` volume and are installed once by `./lab bootstrap --only fl`.

## 7. Virtual networking (Module E)

`experiments/virtual-networking/attach-port.sh boards|list|attach` talks to the IoTronic networking API. The
networking back end (Neutron/Designate) is **not** part of this lab, so `list` returns an empty port list: use it to
demonstrate the API surface, not a working overlay.

## Adding your own boards

* Another Docker board: *Create LR Container* in Horizon, or `lab-ops/01-run-manual-lr.sh` (see [lab-ops/README.md](../lab-ops/README.md)).
* A physical board running Lightning-Rod: point it at `wss://<host>:8181` (realm `s4t`), make `crossbar` and
  `iotronic-wstun` resolve to the lab host, and register it with a board code created in *Boards → Create Board*.
