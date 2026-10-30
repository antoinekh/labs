# infrahub_branching

Infrahub 1.11.9 with a small BGP backbone schema, up to 1,064 routers. Lab of two blog posts:

- [Infrahub branching deep dive: inside the graph, the costs, and the limits](https://blog.antoinekh.dev/posts/infrahub-branching-cost/): what a branch costs (create, read, edit, diff, merge, delete), the raw Neo4j graph behind it, a custom check that gates a maintenance change, and the rollback of a bad merge.
- [Which services sit behind this router? Infrahub Graph Traversal](https://blog.antoinekh.dev/posts/infrahub-graph-traversal/): the services behind a route reflector, and a PCI-DSS path rule as a check.

No containerlab: the lab is the Infrahub release compose file, a Gitea server for the checks repository, and Python scripts that run in a task-worker container with the SDK of the image.

## Layout

| Path | Content |
|------|---------|
| `docker-compose.yml`, `docker-compose.override.yml` | The stack (see [Setup](#1-setup)) |
| `run.sh` | Runs a command in a one-off task-worker container, with this folder on `/lab` |
| `setup/` | The `Net` schema and the data generator |
| `measure/` | The scripts behind every number of the first post |
| `scenarios/` | The scripts of the demos: maintenance gate, rollback, Graph Traversal, PCI-DSS rule |
| `checks-repo/` | The Infrahub repository with the two checks and their queries |
| `results/` | Raw logs, Prefect exports and screenshots, one folder per measurement |

## 1. Setup

### Start the stack

```bash
docker compose -p infrahub-bench up -d --wait
```

- `docker-compose.yml` is the release compose file of [Infrahub](https://github.com/opsmill/infrahub) 1.11.9 (Apache 2.0 license): Infrahub 1.11.9, Neo4j 2026.05.0 Community.
- `docker-compose.override.yml` holds every lab change: it bypasses the Docker proxy for the service names, turns off the Infrahub telemetry, exposes Neo4j on 7474/7687, sets a 10 s checkpoint interval (so the store size on disk is current), and adds a Gitea server on port 3000.
- UI: `http://localhost:8000` (`admin` / `infrahub`). Neo4j Browser: `http://localhost:7474` (`neo4j` / `admin`). Gitea: `http://localhost:3000` (`lab` / `labpassword1`).
- Host of all the measurements: a WSL2 laptop with 15 GB of RAM. The first start took 3 min 13 s, image pulls included.

| Container | Role |
|-----------|------|
| `infrahub-server` | GraphQL and REST API, web UI. 4 gunicorn workers |
| `task-worker` (x2) | Run the Prefect flows: branch creation, diff, merge, rebase, checks, Git import |
| `task-manager` and its PostgreSQL | Prefect server: queues the flows and keeps their state |
| `message-queue` (RabbitMQ) | Message bus, for example the branch registry refresh after a branch change |
| `cache` (Redis) | Cache and distributed locks |
| `database` (Neo4j 2026.05.0 Community) | The graph: all data, all branches, all history |
| `gitea` | Local Git server for the checks repository |

### Load the data

```bash
docker compose -p infrahub-bench run --rm task-worker infrahubctl schema load models/base --wait 30
docker compose -p infrahub-bench run --rm task-worker infrahubctl menu load models/base_menu.yml
docker compose -p infrahub-bench run --rm -e INFRAHUB_MAX_CONCURRENT_EXECUTION=1 task-worker infrahubctl run models/infrastructure_edge.py
./run.sh infrahubctl schema load /lab/setup/net.yml --wait 30
./run.sh python /lab/setup/gen_data.py --sites 2
./run.sh python /lab/setup/gen_data.py --first-site 2 --sites 150
```

The OpsMill demo comes first (its base schema and its data script, both inside the image), then the `Net` schema. The generator builds an ISP backbone: each site has 2 P routers, 4 PE routers and 1 route reflector (RR). Every PE has a /31 interco to both local P routers, the RR too, and the P routers chain to the next site. Every PE has two iBGP sessions: one to its local RR and one to the RR of Paris (`rr-par-01`), or of Lyon (`rr-lys-01`) for the Paris PEs. Each PE carries two application services.

| Step | Content | Nodes | Relationships | Store on disk | Time |
|------|---------|------:|--------------:|--------------:|-----:|
| Empty Infrahub | core schema only | 19,102 | 51,281 | 5.7 MB | |
| Demo schema | OpsMill base models | 26,334 | 70,979 | 26.8 MB | 58 s |
| Demo data | 5 sites, 30 devices, 100 BGP sessions | 46,260 | 122,838 | 47.3 MB | 7 min 26 s |
| `Net`, small | 2 sites, 14 routers, 26 intercos, 32 sessions, 16 services | 48,732 | 128,642 | 49.9 MB | 14 s |
| `Net`, large | + 150 sites: 1,050 routers, 1,948 intercos, 2,400 sessions, 1,200 services | 150,967 | 336,278 | 164.9 MB | 9 min |

An empty Infrahub already holds 19,102 nodes and 51,281 relationships: the schema itself lives in the graph, with the same versioning as the data. Raw results: `results/setup/`.

### Add the checks repository

Gitea runs next to Infrahub on the same Docker network, so the checks repository never leaves the laptop. Create the `lab` user and the `network-checks` repository, then push the content of `checks-repo/`:

```bash
docker exec -u git infrahub-bench-gitea-1 gitea admin user create --username lab --password labpassword1 --email lab@example.com --must-change-password=false
curl -u lab:labpassword1 -H 'Content-Type: application/json' -d '{"name": "network-checks"}' http://localhost:3000/api/v1/user/repos
tmp=$(mktemp -d) && cp -r checks-repo/. "$tmp" && cd "$tmp"
git init -b main && git add . && git commit -m "add the checks"
git push http://lab:labpassword1@localhost:3000/lab/network-checks.git main
```

Then add it in Infrahub (Integrations, Git Repositories) as a read-only repository on `http://gitea:3000/lab/network-checks.git`. Infrahub imports the check definitions within a minute.

To import a new commit, set that commit on the `network-checks` repository object, then create the branch: a branch created before the import keeps the old commit until you rebase it.

## 2. Measurements

Each line is one table of the first post. Run the Python scripts with `./run.sh python /lab/measure/<script>`. Run the two shell scripts on the host, because they call `docker exec` and `docker stats`.

| Post section | Script | How it was run | Raw result |
|--------------|--------|----------------|------------|
| Data sizes (the table above) | `measure.sh` | after each load step, with a label | `results/setup/measures.log` |
| Measurement 1: creating a branch | `bench_branch.py` | `--prefix large --count 25`, and the same on the small graph | `results/create/bench-*.log` |
| Measurement 1: flow queue and run time | `prefect_runs.py` | on a JSON export of the branch creation flow runs, read from the Prefect API | `results/create/prefect-create-branch-*.json` |
| Measurement 1: memory per branch | `memstats.sh` | with 1 branch, then with 26 | `results/create/memory.log` |
| Measurement 2: reading a branch | `bench_read.py` | defaults: 1,000 changed routers, 7 runs | `results/read/bench-read.log` |
| Measurement 3: editing, diff and merge | `bench_merge.py` | `10 100 1000` | `results/merge/bench-merge.log` |
| Measurement 4: deleting a branch | `branch_admin.py` | one prefix of 25 branches at a time, under `time` | `results/delete/delete-*.log` |

`measure.sh` waits 15 s before it reads the store, so run it after a step, not during one.

## 3. Scenarios

The scenarios are the parts of the posts that show a workflow, not a number. The screenshots of both posts are in `results/screenshots/`.

### Maintenance gate (first post)

On a branch `maint-rr-lys-01`, set `rr-lys-01` to `maintenance` in the UI and open a proposed change. The check `pe_route_reflector_redundancy` fails for the 8 PEs that peer with `rr-lys-01`, and the merge is refused. The fix, on the same branch, gives each of these PEs a session to a third RR:

```bash
./run.sh python /lab/scenarios/add_backup_rr.py --branch maint-rr-lys-01 --drained rr-lys-01 --backup rr-mrs-01
```

Then press Retry all in the proposed change: the checks pass and the merge goes through. The conflict and the rebase of the post were done in the UI.

### Rollback (first post)

Infrahub 1.11.9 has no revert, so a rollback is a new branch that writes back the state of `main` before the bad merge. `rollback_demo.py` merges a bad cleanup through a proposed change: three Lyon services go to `low`, and `svc-pe-lys-02-2` is deleted. It prints the time before the merge.

```bash
./run.sh python /lab/scenarios/rollback_demo.py
./run.sh python /lab/scenarios/rollback.py --before 2026-10-30T07:34:50Z --after 2026-10-30T07:40:00Z --branch rollback-cleanup-lys
# open a proposed change from rollback-cleanup-lys, check the diff, merge it
```

`rollback.py` diffs `main` with itself between `--before` and `--after` (`DiffUpdate`, then `DiffTree`), reads each changed object on `main` at `--before`, and writes it back on the rollback branch: attributes set back, deleted objects created again (with a new id), added objects deleted. It reports relationships that differ from their state at `--before`.

### Services behind a router (second post)

```bash
./run.sh python /lab/scenarios/impact.py rr-lys-01
./run.sh python /lab/scenarios/impact.py rr-lys-01 --branch maint-rr-lys-01
```

It prints the application services reachable from the router, and the path to the first five. Change `--depth` (5 by default) to see the cost of depth.

### PCI-DSS rule (second post)

The `pci_firewalls` check fails when a PCI-DSS service reaches a PE through a path that does not cross a PCI-DSS certified firewall. It finds the PEs within 5 hops with the Dependency mode, then reads every path to each PE with the Path mode. The schema has the `firewall` role and `pci_certified` on `NetDevice`, and `compliance` on `NetAppService`.

```bash
./run.sh python /lab/scenarios/pci_demo.py firewalls                          # main: fw-par-01 (certified) and fw-par-02, each linked to pe-par-01
./run.sh infrahubctl branch create pci-onboarding --no-sync-with-git
./run.sh python /lab/scenarios/pci_demo.py onboard --branch pci-onboarding    # svc-pe-par-01-1 becomes PCI-DSS, attached to pe-par-01 and fw-par-02
# open a proposed change: the check fails with two paths
./run.sh python /lab/scenarios/pci_demo.py fix --branch pci-onboarding        # svc-pe-par-01-1 attached to fw-par-01 only
# Retry all in the proposed change: all checks pass
```

The first traversal queries on a new branch take about 16 s each, so the first run of the check can hit the 60 s check timeout: press Retry all.

## Files

| File | Role |
|------|------|
| `setup/net.yml` | `Net` schema: router, interface, interco, BGP session (with `peer`), application service |
| `setup/gen_data.py` | Generates sites (2 P, 4 PE, 1 RR each), /31 intercos, iBGP sessions to two RRs, and services |
| `measure/measure.sh` | Store size, node and relationship counts, branch count |
| `measure/memstats.sh` | Memory of the server, task workers and Neo4j |
| `measure/bench_branch.py` | Times branch creation and edits, counts the graph delta |
| `measure/bench_read.py` | Times the same list query on main and on branches |
| `measure/bench_merge.py` | Times edit, diff and merge for N changes |
| `measure/branch_admin.py` | Deletes the branches with a name prefix |
| `measure/prefect_runs.py` | Queue and run time of Prefect flows from a JSON export |
| `scenarios/add_backup_rr.py` | On a branch, adds a session to a backup RR for every PE of a drained RR |
| `scenarios/impact.py` | Application services reachable from a router (Graph Traversal API) |
| `scenarios/pci_demo.py` | PCI-DSS rule demo: `firewalls` (on main), `onboard` and `fix` (on a branch) |
| `scenarios/rollback_demo.py` | Merges a bad cleanup of the Lyon services, to have something to roll back |
| `scenarios/rollback.py` | Builds a rollback branch from the diff of `main` between two times and its state before |
| `checks-repo/.infrahub.yml` | Declares the two queries and the two checks |
| `checks-repo/checks/route_reflector_redundancy.py` | No PE may keep fewer than two active route reflectors |
| `checks-repo/checks/pci_firewalls.py` | Every path from a PCI-DSS service to a PE crosses a certified firewall |

## Gotchas

- **Demo data load at the default concurrency.** The first load failed halfway: one mutation returned HTTP 500 with the Neo4j error "The transaction read outdated data and cannot be recovered due to concurrent data modification. Retry the transaction." Infrahub passes the transient error to the client instead of retrying it, and the demo script is not idempotent, so reset the database and load again with `INFRAHUB_MAX_CONCURRENT_EXECUTION=1` (the SDK batch concurrency), as above.
- **A diff of `main` between two times hides deletions.** In 1.11.9 it reports a deleted object as updated, with an empty label and a wrong old value, so `rollback.py` checks existence itself. `DiffTree` with the id of a merged proposed change returns the empty `main` side of the diff, not the branch side.
- **Client timeout after a restart.** The server loads the schema of every branch at start-up, and the first mutations can pass the 60 s SDK timeout. Set `INFRAHUB_TIMEOUT=300` in the container (`docker compose -p infrahub-bench run --rm -v "$PWD:/lab" -e INFRAHUB_TIMEOUT=300 task-worker ...`).
- **Store size on disk.** Neo4j writes its store files at a checkpoint, by default every 15 minutes, and the `db.checkpoint()` procedure is Enterprise only, so the size on disk does not move after a step. The override sets `db.checkpoint.interval.time` to 10 s.

## Notes on the results

- The logs show the commands as they ran, when the scripts were at the root of the lab (for example `/lab/branch_admin.py`).
- In `results/setup/measures.log`, the first three lines (before 17:28) come from a first stack whose demo data load failed, and were taken before the checkpoint fix: their store sizes are wrong.
- The first branch series (`results/create/bench-small.log`, `results/create/bench-small-20.log`) ran just after the `Net` schema load, while the workers reported the schema not in sync; the later series ran after a restart.
- Most measurements are one series of 7 to 25 runs on one machine: read them as orders of magnitude, not as a benchmark.
- Client times include the SDK polling; flow queue and run times come from the Prefect API.
- Store sizes are taken 15 s after each step, with a 10 s checkpoint interval.
- The internals described in the posts come from the source code of the tested version (tag `infrahub-v1.11.9`) and the Infrahub developer documentation.

## Stop and clean

```bash
docker compose -p infrahub-bench down        # keep the data
docker compose -p infrahub-bench down -v     # delete the data
```
