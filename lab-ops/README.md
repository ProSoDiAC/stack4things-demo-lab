# Lab ops — Stack4Things manual Lightning-Rod scripts

Operational helpers for manually managed Lightning-Rod containers (extra boards beyond the six in the compose file).
Network details: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#network).

## Credentials

| Item | User / Pass |
|------|-------------|
| Horizon | `admin` / `s4t` |
| Lightning-Rod UI | `me` / `arancino` |
| SSH **inside** LR (script `01`) | `root` / `arancino` (override `ROOT_PASS`) — **no** host SSH port published |

## Lab host IP

The scripts read `S4T_LAB_HOST` (set by `./lab init` in `.env` / `vm-ip.txt`) for the URLs they print.
WoT demos use `http://<host>:<public_port>/`.

## Lightning-Rod ports (important)

Inside **every** Lightning-Rod container the dashboard listens on **1474**.  
On the host each board has a **different** published port mapped to that 1474:

| Board | Container | Browser URL |
|-------|-----------|-------------|
| board-alpha | lightning-rod | `http://<host>:1474/` |
| board-beta | lightning-rod-2 | `http://<host>:1475/` |
| board-gamma | lightning-rod-3 | `http://<host>:1476/` |
| board-delta | lightning-rod-4 | `http://<host>:1477/` |
| board-epsilon | lightning-rod-5 | `http://<host>:1478/` |
| board-zeta | lightning-rod-6 | `http://<host>:1479/` |
| manual boards | `lightning-rod-<name>` | `http://<host>:1482+` (from `01`) |

Host `:1474` is **alpha only**. Use `./04-list-lr-dashboards.sh` for the full map.

## Scripts

| Script | Purpose |
|--------|---------|
| `00-verify-demo.sh` | Health-check + repair |
| `01-run-manual-lr.sh` | Create IoTronic board + start LR **without** auto-register; installs `sshd` in-container |
| `02-destroy-manual-lr.sh` | Remove LR (+ `--delete-board`) |
| `03-print-lr-info.sh` | IP / ports / board mapping |
| `04-list-lr-dashboards.sh` | Board → dashboard URL list |
| `env.sh` | Shared defaults |

```bash
cd lab-ops

./00-verify-demo.sh
./04-list-lr-dashboards.sh

BOARD_NAME=lab-edge-1 ./01-run-manual-lr.sh
# Open the printed URL (e.g. http://<host>:1482/)
# Config: WAMP=wss://crossbar:8181  Code=<printed>  Hostname=lab-edge-1

./02-destroy-manual-lr.sh --delete-board
```

## Manual registration (after `01`)

1. Open the **host port** URL printed by the script (not always `:1474`)
2. First-boot Config:
   - **WAMP / urlwagent** = `wss://crossbar:8181` (Docker network LR containers)
   - **Code** = printed registration code
   - **Hostname** = board name
3. CONFIGURE → board becomes online in Horizon

For **external** boards (outside Docker): do not rely on Docker DNS alone —
add `/etc/hosts` entries for `crossbar` / `iotronic-wstun` pointing at `<host>`
(see [docs/DEMOS.md](../docs/DEMOS.md#adding-your-own-boards)).

## SSH inside the container

From the lab host after `01`:

```bash
ssh root@<DOCKER_IP>          # password arancino
# or
docker exec -it <CONTAINER> bash
```

No `-p 22:22` on the host.

## Pre-session checklist

1. `./00-verify-demo.sh` → `READY` (same as `../lab verify`)
2. `./04-list-lr-dashboards.sh` → clear URLs for your `<host>`
3. WoT demos: the public URLs listed in *IoT → Web Services*
4. Metrics / FL / Web Services as required by the session
