# airflow-platform — Docker Compose stack

A second way to run this repo's Airflow platform: same DAGs, same per-team
isolation model, same Keycloak SSO, **no Kubernetes**. Apache Airflow 3.3.1 on
`CeleryExecutor`, brought up with one `make up`.

**This directory is self-contained.** Its own `dags/`, `roles/`,
`reconcile_roles.py`, `sso/` realm and `tests/`; nothing in it reads anything
outside `compose/`, so the folder can be lifted into its own repo as-is. The
repo root is a separate Kubernetes stack carrying its own copies — the two
evolve independently, and a change to one does not touch the other.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin
  (`docker compose version` ≥ 2)
- Roughly 7 GB of memory available to Docker (three worker classes + Postgres +
  Redis + Keycloak + five Airflow services)

## Quickstart

```
cd compose
make up
```

This builds the CVE-hardened image, starts Postgres, Redis and Keycloak (which
imports the `airflow` realm), runs the migrations, creates the team roles,
brings up the api-server / scheduler / dag-processor / triggerer and the three
worker classes, then applies each DAG's `access_control`.

Then open <http://localhost:8080>, click **Sign in with keycloak**, and log in
as one of the realm users (username == password):

| User    | Keycloak group  | Airflow role | Sees                   |
|---------|-----------------|--------------|------------------------|
| `alice` | `airflow-team-a` | `team_a`    | `team_a_pipeline` only |
| `bob`   | `airflow-team-b` | `team_b`    | `team_b_pipeline` only |
| `carol` | `airflow-team-c` | `team_c`    | `team_c_pipeline` only |
| `admin` | `airflow-admins` | `Admin`     | every DAG              |

The Keycloak admin console is at <http://localhost:8181> (`admin`/`admin`).

`make down` stops the stack and keeps the metadata database; `make clean` also
deletes it. Keycloak runs `start-dev` with an in-memory database, so the realm
is re-imported from `sso/realm-airflow.json` on every start regardless.

## What this stack drops, and what replaced it

Everything removed here was a Kubernetes-shaped concern, not an Airflow one.
Keycloak / OIDC SSO is **not** on the list — it is kept, as the `keycloak`
service (see [SSO](#sso) below):

| Dropped                        | Replaced by                                                                 |
|--------------------------------|-----------------------------------------------------------------------------|
| Vault                          | Literals in `.env` — one file, still throwaway local-dev values             |
| MinIO remote task logging      | A shared `airflow-logs` volume every service mounts                         |
| Postgres 1 primary + 2 replicas, `failover.sh` / `failback.sh` | One `postgres:16` container — there is nothing to fail over to |
| PgBouncer discussion, `max_connections` tuning | Stock Postgres settings; a laptop-sized deployment never reaches them |
| Helm chart, `kind`, NodePorts  | `docker-compose.yaml` and a published port                                  |
| `KubernetesExecutor` (per-task pods) | Nothing — route with `queue=` to a worker class instead              |

## SSO

Sign-in goes through Keycloak, exactly as in the `kind` stack — same realm
(`sso/realm-airflow.json`), same groups, same group → role mapping. What differs
is only the packaging:

| | `kind` stack | this stack |
|---|---|---|
| Keycloak | Deployment + Service + realm ConfigMap | one `keycloak` compose service, realm bind-mounted |
| Client secret | Vault → rendered into the realm + a k8s Secret | `AIRFLOW_KEYCLOAK_CLIENT_SECRET` in `.env`, into both the realm and `webserver_config.py` |
| FAB config | `apiServerConfig` in `values.yaml`, via Helm `tpl` | `config/webserver_config.py`, bind-mounted into every component |
| One Keycloak URL for browser **and** pod | socat sidecar publishing `127.0.0.1:8181` in the pod | `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` on the `keycloak` service |

**The URL split.** authlib rejects a token whose `iss` claim differs from the
`issuer` it read from OIDC discovery. The browser reaches Keycloak at
`http://localhost:8181`; the Airflow containers reach it at `http://keycloak:8080`.
`KC_HOSTNAME` keeps `issuer` and `authorization_endpoint` fixed at
`http://localhost:8181` — so the browser redirect works and every token's `iss`
still equals the discovery `issuer` — while `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`
rewrites the token / userinfo / JWKS endpoints per request, so the api-server
fetching discovery on `keycloak:8080` gets back `keycloak:8080` URLs it can
actually reach. No proxy needed.

## How the isolation works

The mechanism is the same as the `kind` stack's. Three pieces have to line up:

1. **Team roles hold no global DAG permission.** The per-project role files under
   `roles/` give each team role the built-in Viewer permissions
   **minus** `can_read` on the global `DAGs` resource. That single omission is
   the whole mechanism — `FabAuthManager._is_authorized_dag()` short-circuits to
   "allow everything" for anyone holding it.
2. **Group membership picks the role.** `config/webserver_config.py` sets
   `AUTH_ROLES_MAPPING` (`airflow-team-a` → `team_a`, …, `airflow-admins` →
   `Admin`) and `AUTH_ROLES_SYNC_AT_LOGIN = True`, so the `groups` claim is
   re-read on every login and the user's roles rewritten to match. To move
   someone between teams, change their group in Keycloak — nothing in Airflow.
3. **Each DAG grants itself to one role.** Every team DAG declares
   `access_control={"team_x": {"can_read", "can_edit"}}`, which
   `airflow sync-perm --include-dags` turns into a `DAG:<dag_id>` permission on
   that role.

A DAG with no `access_control` is visible to nobody but `Admin` — that covers
`hello_world` and the three `hello_<class>` DAGs. A user in no mapped group
lands on `Public` and sees nothing.

`AIRFLOW__CORE__AUTH_MANAGER` is set to `FabAuthManager` in
`docker-compose.yaml`. Airflow 3 defaults to `SimpleAuthManager`, which has no
roles or per-DAG permissions at all — without that setting the whole model above
silently does nothing.

Local FAB users (`bootstrap/init.sh`) are off by default (`CREATE_LOCAL_USERS`):
under `AUTH_TYPE=AUTH_OAUTH` the login form is gone, so they could never sign in.
Flip that var only if you also strip the SSO wiring back out.

### Why bootstrap is two services

`airflow-init` runs migrations and imports and reconciles the roles (the
`AUTH_ROLES_MAPPING` targets must exist before anyone logs in). Everything else
`depends_on` it with `service_completed_successfully`, so nothing starts against
an unmigrated database.

`airflow-bootstrap` runs `airflow sync-perm --include-dags` and waits on the
api-server, scheduler and dag-processor being healthy. It cannot be folded into
`airflow-init`: `sync-perm` reads `access_control` from the **serialized** DAGs in
the database, not from the files on disk, and nothing has serialized them until
the dag processor has made a pass — which cannot happen until init finishes.

Both exit when done, so `docker compose ps` showing them as `exited` is the
expected steady state.

Both are idempotent, so `make up` on an existing stack is safe. Note that
`init.sh` will not change the role on a user that already exists — the metadata
volume outlives `make down`, so edit the user directly, or `make clean` first.

## Worker classes

Three worker containers, one per Celery queue, mirroring the three worker
Deployments the `kind` stack renders from `airflow.workers.celery.sets`:

| Service                 | Queue    | Caps (`.env`)                     |
|-------------------------|----------|-----------------------------------|
| `airflow-worker-small`  | `small`  | `WORKER_SMALL_CPUS` / `_MEM`      |
| `airflow-worker-medium` | `medium` | `WORKER_MEDIUM_CPUS` / `_MEM`     |
| `airflow-worker-large`  | `large`  | `WORKER_LARGE_CPUS` / `_MEM`      |

Routing is identical to the `kind` stack, because it is a property of the DAG,
not of the deployment:

```python
with DAG(..., default_args={"queue": "medium"}):   # whole DAG
    @task(queue="large")                            # single task
```

A task with no `queue` lands on `small` (`AIRFLOW__OPERATORS__DEFAULT_QUEUE`).

The chart's values were Kubernetes requests plus a memory limit; `.env` sets hard
container caps, so they are sized at roughly the chart's *limit* rather than its
request.

## Changing DAGs

`dags/` is bind-mounted, so there is no image rebuild and no restart: edit a
file and the dag processor picks it up on its next pass.

`dags/` holds one folder per project, each a self-contained Python package with
its own `common/` subpackage. `dags/` is on `sys.path`, so imports are
project-prefixed (`from demo.common.greetings import where`) — which is what
keeps two projects' helpers from colliding. Keep non-DAG modules under
`common/`; the processor parses every top-level `.py` in a project folder
looking for DAG objects.

Adding or changing a DAG:

1. Add or edit a file under `dags/<project>/`, with an `access_control` entry
   naming a role defined in `roles/<project>.json`.
2. Update `tests/test_<project>/manifest.py` (`EXPECTED_DAG_IDS`, and
   `TEAM_DAG_ROLE` / `QUEUE_DAG_CLASS` / `NO_ACL_DAG_IDS` as applicable) — the
   tests assert against it.
3. `make up`, which re-runs the bootstrap. Two things need it: a **new role**,
   and a **new or changed `access_control`** (`sync-perm` has to run again).

Adding a whole project also needs `dags/<project>/__init__.py` +
`common/__init__.py`, a `roles/<project>.json`, and a `tests/test_<project>/`
(copy `test_dags.py` — it is generic, driven entirely by `manifest.py`).
`tests/test_projects_global.py` fails if a `dags/<project>/` has no matching
`tests/test_<project>/manifest.py`, so a half-added project can't slip through.

## Testing

`make test` runs this stack's own suite (`tests/`) inside this stack's own
image, so no local Airflow install is needed. The suite reads only `dags/` and
each project's `tests/test_<project>/manifest.py` — never `docker-compose.yaml`
or `roles/`. Keeping those in step with the DAGs (a role in
`roles/<project>.json` for every role a DAG grants, an `airflow-worker-<class>`
service for every `queue=`) is a deploy concern, covered by the `make up` smoke
run.

One check matters especially here: `test_no_task_names_an_executor`. This stack
configures `CeleryExecutor` alone, and an executor a task names but the
deployment does not configure is a hard DAG **parse** error, not a run-time one
— so it would take the DAG out of the UI entirely.

## Files

| File                       | Purpose                                                                       |
|----------------------------|--------------------------------------------------------------------------------|
| `docker-compose.yaml`      | The whole stack; carries the reasoning for every non-obvious setting            |
| `.env`                     | Single source of truth for image tags, secrets, ports, worker caps              |
| `Dockerfile`               | CVE-hardened image (no `COPY dags/` — they are bind-mounted; no socat)          |
| `Makefile`                 | Thin `docker compose` wrapper; `make help` lists targets                        |
| `dags/`                    | This stack's DAGs, one folder per project (`demo/`), bind-mounted at run time   |
| `roles/`                   | One role file per project; imported and reconciled by `bootstrap/init.sh`       |
| `sso/realm-airflow.json`   | Keycloak realm — groups, `airflow` OIDC client, four demo users; imported on every start |
| `config/webserver_config.py` | FAB auth config (Keycloak SSO); bind-mounted into every Airflow component       |
| `bootstrap/init.sh`        | Migrations, role import + reconcile, (opt-in) local user creation               |
| `bootstrap/sync-perm.sh`   | Waits for DAG serialization, then applies each DAG's `access_control`           |
| `bootstrap/reconcile_roles.py` | Gap-free reconcile of the role files against the live DB (delta only, add-before-delete, refuses FAB built-ins) |
| `tests/`                   | Unit tests for `dags/`; sits beside it, so the dag processor never sees them    |
| `pytest.ini`               | Test config; `make test` mounts it into the image                               |

## Targets

| Target                | Description                                                    |
|-----------------------|-----------------------------------------------------------------|
| `make up`             | Build and start everything (default entry point)                |
| `make down`           | Stop the containers, keep the metadata DB and logs              |
| `make build`          | Build the CVE-hardened image                                    |
| `make rebuild`        | Rebuild with no layer cache (picks up new Debian CVE fixes)     |
| `make ps`             | Container status                                                |
| `make logs`           | Tail every service                                              |
| `make logs-scheduler` | Tail the scheduler only                                         |
| `make logs-keycloak`  | Tail Keycloak (realm import, login errors)                      |
| `make shell`          | Shell in a throwaway container with the Airflow CLI             |
| `make test`           | Run this stack's `dags/` unit tests inside its own image         |
| `make clean`          | Stop everything and delete the volumes                          |

## Credentials

Every secret in `.env` is a hardcoded local-development value, exactly as in the
`kind` stack — moving them out of Vault changed *where* they live, not that they
are throwaway. Replace `AIRFLOW_FERNET_KEY`, `AIRFLOW_API_SECRET_KEY`,
`AIRFLOW_KEYCLOAK_CLIENT_SECRET`, the Keycloak admin password and the Postgres
credentials in `docker-compose.yaml` before this is reachable by anyone but you.
The four realm users' passwords live in `sso/realm-airflow.json` (username ==
password); change them there.
