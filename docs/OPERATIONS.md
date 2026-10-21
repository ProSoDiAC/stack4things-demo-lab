# Operations

## Configuration

`./lab init` creates `.env` from `.env.example`. The values worth knowing:

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `s4t` | prefix of the network and every volume (`s4t_lr_var`, …). Changing it creates a *new, empty* lab |
| `S4T_LAB_HOST` | first host IP | address printed in URLs and used by the helper scripts for public ports |
| `BIND_PUBLIC` / `BIND_INTERNAL` | `0.0.0.0` / `127.0.0.1` | which interface the two groups of published ports bind to ([architecture](ARCHITECTURE.md#network)) |
| `S4T_SUBNET`, `S4T_GATEWAY` | `10.250.0.0/24`, `10.250.0.1` | subnet of the lab network; change it if it clashes with yours |
| `GRAFANA_ADMIN_PASSWORD`, `LAB_SSH_PASSWORD`, `LAB_SSHD` | `admin`, `arancino`, `1` | Grafana admin, root password of the in-board sshd, and whether sshd is started at all |
| `IMG_*` | pinned digests | upstream images |

The service credentials (Horizon `admin/s4t`, MariaDB `root/unime`, RabbitMQ `openstack/unime`, …) are fixed in `conf/`,
the compose file and the helper scripts; they are demo defaults, not parameters.

## Starting, stopping, rebooting

```bash
./lab up           # idempotent: starts/updates whatever is not running
./lab down         # stops and removes containers, KEEPS all data
./lab down && ./lab up                       # same state as before
docker compose up -d --force-recreate        # brand-new containers on the same data
```

All containers have `restart: unless-stopped` and Docker is enabled at boot, so a host reboot brings the lab back
by itself (about 30-60 s until `./lab verify --check-only` reports READY; the first start after re-creating a
Lightning-Rod also re-installs sshd, which takes a minute more).

This was tested explicitly: `./lab down && ./lab up`, `systemctl restart docker` and
`docker compose up -d --force-recreate` all returned to *READY* without any manual step.

## Backup and restore

```bash
./lab backup                       # -> backups/<timestamp>/  (databases.sql + one tgz per volume)
./lab down
./lab restore backups/<timestamp>  # recreates the volumes, starts the stack, loads the SQL dump
./lab verify
```

The database is restored from the SQL dump (consistent), everything else from volume archives. Logs are skipped.

## Upgrading

Images are pinned. To move to newer upstream images, change the `IMG_*` digests in `.env`, then
`./lab up && ./lab verify`. After editing patches in `patches/` or `entrypoints/`, recreate the affected container
(`docker compose up -d --force-recreate iotronic-ui`) — they are bind mounts, not part of any image.

## Migrating an existing deployment

If you already run the upstream `ch13` compose (+ the old lab overlay) you can adopt this repository **on the same data**:

1. `docker compose down` the old stack (no `-v`) and take a backup of the volumes.
2. Set `COMPOSE_PROJECT_NAME=ch13` in `.env`, so the volume names (`ch13_lr_var`, …) match.
3. Start only the database (`docker compose up -d --wait iotronic-db`) and make the agent identity stable:
   `UPDATE wampagents SET hostname='iotronic-wagent' WHERE hostname='<old agent container id>';`
   `UPDATE boards SET agent='iotronic-wagent' WHERE agent='<old agent container id>';`
4. `./lab up`, then in every Lightning-Rod replace the old agent id in `/etc/iotronic/settings.json`
   (`docker exec <lr> sed -i 's/<old id>/iotronic-wagent/g' /etc/iotronic/settings.json`) and restart the boards.
5. `./lab bootstrap --only plugins fl verify` refreshes the plugin code and heals the demos.

Keystone's Fernet keys are regenerated on the first start (tokens issued before are invalid; users log in again).

## Security

The lab is a demo environment:

* Default credentials are public (see the README). Do not publish the host on the internet as is.
* Admin surfaces (databases, Keystone/Conductor APIs, RabbitMQ, InfluxDB, FL/metrics control, LR proxy) bind to
  loopback by default. `lr-log-proxy` has the Docker socket and every Lightning-Rod runs `privileged` with the Docker
  socket mounted — anyone who can run a plugin on a board controls the host. Keep the lab on a trusted network.
* The Lightning-Rod UIs (1474-1479) and the in-board sshd (reachable through WSTUN ports 50001-50100) use the
  default `me/arancino` and `root/arancino` passwords. Set `LAB_SSHD=0` or change `LAB_SSH_PASSWORD` before
  exposing them, or restrict `BIND_PUBLIC`.
* To open the admin ports to a trusted LAN set `BIND_INTERNAL=0.0.0.0`.

## Troubleshooting

| Symptom | Check |
|---|---|
| Horizon login fails | `docker logs keystone` (should end with `[keystone-init] ready`); `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/v3` must be 200 |
| A board stays *offline* | `docker logs <lightning-rod container>`; `./lab verify` restarts it; the board's registration code must match (`board-<name>-lab2026`) |
| `./lab up` times out | `docker compose ps` shows which container is unhealthy; `./lab logs <service>` |
| *no live metrics streams* | `docker exec lightning-rod tail /var/log/iotronic/lightning-rod.log`; re-run `./lab bootstrap --only metrics` |
| `ports are not available` | another service uses one of the host ports listed in the README |
| FL clients cannot reach the server | the Flower server must be running (`curl http://127.0.0.1:8091/api/fl/status`); clients use `fl-control:8087` on the lab network |
| Need a clean slate | `./lab reset` then `./lab up && ./lab bootstrap` |

`./lab verify` is the first thing to run: it checks containers, endpoints, the conductor patch, boards, plugins,
metrics, WSTUN services and FL, and repairs what it can (restart, re-expose services, restart streams).

## Tests

`tests/run-all.sh` (see README) is the acceptance suite. It is what was run after each of the persistence
experiments above and on a fresh clone.
