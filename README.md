# Stack4Things demo lab

A self-contained, reproducible **[Stack4Things](https://github.com/MDSLab) (IoTronic)** environment for demos and
hands-on training: the full control plane (Keystone, IoTronic conductor + WAMP agent, Horizon UI), six virtual
**Lightning-Rod** boards, and ready-made demos — plugins, web services over WSTUN, metrics (InfluxDB + Grafana),
federated learning (Flower), fleets and on-demand boards.

Everything runs in Docker on a single machine. One command brings it up, one command populates the demos, and the
whole thing **survives restarts, reboots and container re-creation** (all state lives in named volumes; startup is
idempotent and ordered by health checks).

```bash
git clone https://github.com/ProSoDiAC/stack4things-demo-lab.git
cd stack4things-demo-lab
./lab init <ip-or-hostname-users-will-use>   # optional, defaults to this machine's first IP
./lab up          # pulls images (≈ 9 GB the first time), builds 3 small helper images, starts 20 containers,
                  # waits until healthy (≈ 1 min once the images are cached)
./lab bootstrap   # creates boards, plugins, metrics stream, web services, FL deps (≈ 3 min, downloads PyTorch)
./lab verify      # health report (self-heals what it can) -> "RESULT : READY"
```

Then open **`http://<host>/horizon`** and log in as `admin` / `s4t` (domain `Default`).

## What you get

| | |
|---|---|
| **Control plane** | Keystone, MariaDB, RabbitMQ, Crossbar (WAMP over TLS), WSTUN, IoTronic conductor + agent, Horizon with lab panels |
| **Boards** | `board-alpha` … `board-zeta`: six virtual Lightning-Rods, all online and registered after `./lab bootstrap` |
| **Plugins** | `HelloName` (synchronous), `EnvironmentalDemo` (asynchronous, streams a real sensor dataset), `fl-client-heart`, `fl-client-pm` |
| **Web services** | weather API, WoT "Fritzing" UI + API, nginx demo, SSH — exposed through WSTUN public ports |
| **Metrics** | board → metrics-gateway → InfluxDB → Grafana, embedded in Horizon (*IoT → Metrics*) |
| **Federated learning** | Flower server + live dashboard, 3 boards training heart-disease / predictive-maintenance models (*IoT → Federated Learning*) |
| **Fleets & on-demand boards** | create fleets, run plugins on whole fleets, and spin up a new Lightning-Rod container from the Boards page |
| **Tools** | `./lab` CLI, backup/restore, self-healing verifier, end-to-end test suite |

### Credentials (lab defaults)

| Service | URL | User / password |
|---|---|---|
| Horizon | `http://<host>/horizon` | `admin` / `s4t` (domain `Default`) |
| Grafana | `http://<host>:3000` | `admin` / `admin` (anonymous viewer enabled for the embedded dashboards) |
| Lightning-Rod UI | `http://<host>:1474` … `:1479` (alpha … zeta) | `me` / `arancino` |
| SSH in boards (over WSTUN) | port shown in *IoT → Services* | `root` / `arancino` |

These are demo credentials baked into the configuration. Do not expose the lab on an untrusted network
(see [Security](docs/OPERATIONS.md#security)).

## Requirements

* Linux host, **Docker Engine ≥ 24** and the **Compose v2** plugin (tested with Docker 28.0 / Compose 2.33)
* ≈ 8 GB RAM, ≈ 20 GB free disk (images ≈ 9 GB, plus volumes), internet access on first start (image pulls,
  Python wheels for the FL clients, the sample dataset)
* `python3` ≥ 3.8 on the host (standard library only) for `./lab bootstrap` / `verify`; `curl`
* Free host ports: `80, 3000, 8080, 8181, 50001-50100, 1474-1479` (public) and `3306, 5000, 5672, 15672, 8086,
  8090-8093, 8812` (loopback only by default)

## The `./lab` CLI

| Command | What it does |
|---|---|
| `./lab init [HOST]` | create `.env` from `.env.example`, set `REPO_ROOT` and the host address used in printed URLs |
| `./lab up` | build + start everything, wait for health checks |
| `./lab bootstrap [--only boards plugins fl metrics services verify]` | populate the demos; idempotent, safe to re-run |
| `./lab verify [--check-only]` | check every layer (containers, HTTP, boards, plugins, metrics, WSTUN services, FL) and heal |
| `./lab urls` | print URLs and credentials |
| `./lab ps / logs [svc] / restart [svc] / down` | usual Compose helpers |
| `./lab backup [DIR]` / `./lab restore DIR` | DB dump + all volumes; see [operations](docs/OPERATIONS.md#backup-and-restore) |
| `./lab reset` | destroy containers **and data** (asks for confirmation) |

## Documentation

* [docs/DEMOS.md](docs/DEMOS.md) — walk-through of each demo, with the commands and what to look at in Horizon
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — services, network, volumes, ports, how persistence works, and what the lab patches
* [docs/OPERATIONS.md](docs/OPERATIONS.md) — configuration, security, backup/restore, upgrades, troubleshooting, tests
* [lab-ops/](lab-ops/README.md) — helper scripts for manually managed Lightning-Rod containers

## Tests

```bash
tests/run-all.sh          # ~2 min: stack health, Horizon login + every panel, metrics E2E,
                          # fleets (37 checks), federated learning (heart + PM), dynamic board lifecycle
tests/run-all.sh quick    # skips the FL training and dynamic-board tests
```

## Repository layout

```
lab                    CLI entry point
docker-compose.yml     the whole stack (single file, pinned image digests, health checks, restart policies)
.env.example           configuration (copy to .env; `./lab init` does it)
conf/                  IoTronic conductor/agent, Horizon, Crossbar configuration
entrypoints/           startup scripts for keystone, conductor, agent, UI and Lightning-Rod containers
docker/                Dockerfiles of the three helper images (metrics gateway, FL control, LR log proxy)
patches/               lab modifications mounted over the upstream images (Horizon panels, conductor fix, Grafana)
plugins/               HelloName and EnvironmentalDemo plugin sources
experiments/           metrics, federated learning, multi-board/fleets, web services (WSTUN), networking helpers
vendor/                small upstream sources the demos need (Flower server, weather server) — see vendor/README.md
scripts/               bootstrap.py, verify-demo.py, backup/restore
tests/                 end-to-end test suite
lab-ops/               scripts for manual Lightning-Rod containers
```

## Provenance and license

Based on the Stack4Things Docker deployment from the
[AssemblingSmartCPS](https://github.com/AssemblingSmartCPS) repositories and the upstream
[MDSLab](https://github.com/MDSLab) images (`mdslab/iotronic-*`, `mdslab/lrod`), which this repository
pulls unmodified (pinned by digest) and customises through bind-mounted patches. See
[vendor/README.md](vendor/README.md) for the few third-party sources included.

Licensed under the [Apache License 2.0](LICENSE).
