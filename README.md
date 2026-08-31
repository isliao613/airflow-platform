# airflow-platform

One-click local deployment of Apache Airflow 3.3.1 (Helm chart 1.22.0) on a
`kind` cluster, with Keycloak SSO and per-team DAG isolation.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [kind](https://kind.sigs.k8s.io/)
- [helm](https://helm.sh/) 3.13 or newer (`helm uninstall --ignore-not-found`)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

## Quickstart

```
make up
```

This creates the `airflow` kind cluster, deploys a dev-mode Vault and seeds it
with this repo's local secret values, deploys Keycloak and imports the
`airflow` realm (rendered from those Vault-backed secrets), deploys a
dev-mode MinIO for Airflow's remote task logging, builds the
CVE-hardened Airflow image from the `Dockerfile`, loads it into the cluster
with `kind load` (no registry push needed), and installs `chart/` -- this
repo's own umbrella Helm chart, which wraps the `apache-airflow/airflow`
chart (pinned to `1.22.0`, from a Docker Hub OCI mirror) as a dependency,
plus its own `templates/sync-roles-job.yaml` -- a post-install/
post-upgrade hook Job that creates the team roles and applies each DAG's
`access_control` once the release installs.

The image build is the slowest step and the one most likely to fail first: it
pulls the `apache/airflow:3.3.1` base image, applies OS updates, and adds
`socat` (for the Keycloak sidecar). What gets deployed is that locally built
`isliao613/airflow:3.3.1-hardened.1`, **not** upstream `apache/airflow:3.3.1`
directly -- see `Dockerfile` for what is patched and why. As of 3.3.1 there is
no Python-package patch: the litellm CVEs that needed one under 3.3.0 are
fixed in the litellm 3.3.1 already bundles.

| Service          | URL                     | Credentials                       |
|------------------|-------------------------|-----------------------------------|
| Airflow UI       | http://localhost:8080   | "Sign in with keycloak"           |
| Keycloak console | http://localhost:8181   | `admin` / `admin`                 |
| Vault UI         | http://localhost:8200   | Root token: `airflow-local-dev-root-token` |

## SSO and per-team DAG isolation

Identities live in Keycloak, not in Airflow. Three groups map to three Airflow
roles, and each role can see exactly one DAG; a fourth group maps to the
built-in `Admin` role, which sees every DAG and can manage users, roles,
connections, and variables:

| Keycloak user | Password | Keycloak group    | Airflow role | Visible DAG(s)      |
|---------------|----------|-------------------|--------------|----------------------|
| `alice`       | `alice`  | `airflow-team-a`  | `team_a`     | `team_a_pipeline`    |
| `bob`         | `bob`    | `airflow-team-b`  | `team_b`     | `team_b_pipeline`    |
| `carol`       | `carol`  | `airflow-team-c`  | `team_c`     | `team_c_pipeline`    |
| `admin`       | `admin`  | `airflow-admins`  | `Admin`      | all three            |

Signing in as `alice` shows one DAG. `team_b_pipeline` and `team_c_pipeline` are
absent from the DAG list, and navigating to their URLs directly returns 403.

### How the isolation actually works

Airflow uses the FAB auth manager (the chart's default) with
`AUTH_TYPE = AUTH_OAUTH` against Keycloak. Four pieces have to line up:

1. **Keycloak puts group membership in the token.** The realm's `airflow`
   client has an `oidc-group-membership-mapper` publishing a `groups` claim,
   with `full.path=false` (bare names, no leading `/`) and
   `userinfo.token.claim=true` -- Flask-AppBuilder's built-in `keycloak`
   handler reads groups from the *userinfo* endpoint, so that last flag is not
   optional.
2. **FAB maps groups to roles.** `AUTH_ROLES_MAPPING` in the
   `webserver_config.py` embedded in `chart/values.yaml` (see
   `airflow.apiServer.apiServerConfig`) turns `airflow-team-a` into the
   `team_a` role, and `AUTH_ROLES_SYNC_AT_LOGIN = True` re-applies it on
   every login -- so moving a user between groups in Keycloak takes effect on
   their next sign-in, with no action in Airflow.
3. **Team roles hold no global DAG permission.** The per-project role files
   under `chart/files/roles/` (e.g. `demo.json`) give each team role the
   built-in Viewer permissions **minus** `can_read` on the
   global `DAGs` resource. That single omission is the whole mechanism:
   `FabAuthManager._is_authorized_dag()` short-circuits to "allow everything"
   for anyone holding it.
4. **Each DAG grants itself to one role.** Every DAG file declares
   `access_control={"team_x": {"can_read", "can_edit"}}`, which
   `airflow sync-perm --include-dags` turns into a `DAG:<dag_id>` permission on
   that role. Listing still works, because Airflow also accepts any `can_read`
   on a `DAG:` resource as permission to list -- and then filters the list down
   to exactly those DAGs.

Steps 3 and 4 are done by `chart/templates/sync-roles-job.yaml`, a
post-install/post-upgrade hook Job defined directly in this repo's own
umbrella chart. It's installed as part of the same Helm release as the
airflow dependency (Helm merges hooks from a root chart and its dependencies
into one ordering for the release), so it can read that release's own
secrets (`airflow-metadata`, and the Fernet key -- now
`vault-airflow-secrets`, see [The Fernet key](#the-fernet-key)) and
`airflow.cfg` (`airflow-config`, needed because that's where `auth_manager`
is set) directly via `.Release.Name` -- no separate config needed. It waits for the
dag processor to serialize the DAG files (`sync-perm` reads `access_control`
from the serialized DAGs in the database, not from the files on disk), then
runs `airflow roles import` and `airflow sync-perm --include-dags`. Helm
always blocks on hook Jobs, so `helm upgrade --install` (i.e. `make deploy`)
doesn't return until this
finishes.

### Where webserver_config.py lives

It's set directly in `chart/values.yaml` as `airflow.apiServer.apiServerConfig`,
rendered through Helm's `tpl` and mounted by the chart -- not baked into the
image. This is safe here because the file has no `{{ }}` Go-template syntax,
only Python's own `{}` dict/f-string literals, which `tpl` ignores.

One quirk to know about: `scheduler`/`worker`/`triggerer`/`dag-processor` all
mount webserver_config.py too (every component needs the same
`AUTH_ROLES_MAPPING` to authorize consistently), but they read
`airflow.webserver.webserverConfig`, not `airflow.apiServer.apiServerConfig`
-- a leftover from the chart splitting `webserver` into `api-server` for
Airflow 3 without updating every component's config-mount key.
`chart/values.yaml` sets both from a single YAML anchor (`&webserverConfig` /
`*webserverConfig`) so there's only one copy to edit.

The upside of this over baking the file into the image: changing SSO config
now only needs `make deploy`, not a full `make build`/`load`/`deploy` cycle.

### Why both sides reach Keycloak at `localhost:8181`

OIDC tokens carry an issuer, and the browser and the Airflow API server have to
agree on it. They reach the same Keycloak by different routes:

- **Browser** -> host port 8181 -> kind `extraPortMapping` -> NodePort 30081
- **API server** -> a `socat` sidecar in its own pod listening on
  `127.0.0.1:8181`, forwarding to the `airflow-keycloak` Service

Both therefore use the literal URL `http://localhost:8181`, so the issuer
matches and no host-side `/etc/hosts` entry is required. The sidecar runs the
Airflow image itself (already in the cluster, with `socat` added by the
`Dockerfile`) rather than pulling a second image just to forward a port.

Changing the host port means changing it in three places: `kind-config.yaml`,
`KC_HOSTNAME` in `sso/keycloak.yaml`, and the sidecar in `chart/values.yaml`.

### The admin group

`airflow-admins` is the one group that maps to a built-in role instead of a
per-team one:

```python
# webserver_config.py, embedded in chart/values.yaml
AUTH_ROLES_MAPPING = {
    "airflow-team-a": ["team_a"],
    ...
    "airflow-admins": ["Admin"],
}
```

`Admin` needs no entry in any `chart/files/roles/*.json` -- it's built into FAB
already, with every permission on every resource. That's also the caveat:
unlike the team roles, `Admin` holds the global `DAGs` permission, so
`admin`/`admin` sees and can edit every team's DAG, and can manage Airflow's
users, roles, connections, and variables through the UI -- the one identity
in this realm that isn't scoped to a single team. Manage Keycloak identities
themselves (adding/removing users or groups) through the Keycloak console.

## Secrets in Vault

The secrets Airflow itself needs to function -- the OIDC client secret,
Airflow's API secret key, the Fernet key, the metadata-database passwords,
and the MinIO credentials + connection for remote task logging -- live in a
dev-mode Vault (`vault/vault.yaml`) instead of
being a literal value in tracked chart/SSO YAML, held together as one Vault
secret (`secret/airflow-platform/airflow`) since they all belong to the
same release. `vault/seed-secrets.sh` is the single source of truth for
the actual VALUES (still hardcoded local-dev values, just centralized in one
file instead of scattered across two); `vault/sync-secrets.sh` reads them
back out and:

- Creates one Kubernetes Secret -- `vault-airflow-secrets`, with keys
  `client-secret`, `api-secret-key`, `fernet-key`, `metadata-db-password`,
  `connection`, `replication-password`, `minio-root-user`,
  `minio-root-password` and `minio-logging-conn` -- consumed via the airflow
  chart's own `apiSecretKeySecretName` / `fernetKeySecretName` /
  `data.metadataSecretName` / `postgresql.auth.existingSecret` / top-level
  `secret:` list
  (`chart/values.yaml`) and by `minio/minio.yaml`,
  the same mechanism the chart already uses for its own metadata/fernet-key
  secrets. Named `vault-*` and deliberately not `airflow-*`: a Secret sharing
  a name the chart itself would ever render (e.g. `airflow-api-secret-key`)
  gets garbage-collected by `helm upgrade` the moment that name drops out of
  the chart's rendered manifest, taking our Vault-sourced Secret down with
  it -- hit this for real switching `apiSecretKey` to
  `apiSecretKeySecretName`.
- Renders `sso/.realm-airflow.rendered.json` from `sso/realm-airflow.json`,
  substituting its `VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER` token -- Keycloak's
  realm import has no equivalent of `secretKeyRef`, so that value has to
  land in the JSON itself. Gitignored and regenerated on every run, same as
  `chart/.values.rendered.yaml`.

Deliberately NOT in Vault: the Keycloak admin login (`sso/keycloak.yaml`)
and the four demo users' passwords (`sso/realm-airflow.json`). Those are
human login credentials, not secrets Airflow's own backend needs to
function, so they stay plain literals -- Vault only holds what's actually
Airflow-side here.

### What's in the secret

`secret/airflow-platform/airflow` holds exactly these nine keys (the values
below are this repo's local-dev literals -- replace them for anything real):

```json
{
  "client-secret": "airflow-local-dev-secret",
  "api-secret-key": "airflow-local-dev-api-secret-key",
  "fernet-key": "YWlyZmxvdy1sb2NhbC1kZXYtZmVybmV0LWtleS0zMmI=",
  "metadata-db-password": "postgres",
  "connection": "postgresql://postgres:postgres@airflow-postgresql-primary:5432/postgres?sslmode=disable",
  "replication-password": "replication-local-dev",
  "minio-root-user": "airflow-logs",
  "minio-root-password": "airflow-logs-local-dev-secret",
  "minio-logging-conn": "{\"conn_type\":\"aws\",\"login\":\"airflow-logs\",\"password\":\"airflow-logs-local-dev-secret\",\"extra\":{\"endpoint_url\":\"http://airflow-minio:9000\",\"region_name\":\"us-east-1\",\"config_kwargs\":{\"s3\":{\"addressing_style\":\"path\"}}}}"
}
```

| Key | Consumed as | By |
|-----|-------------|----|
| `client-secret` | env `AIRFLOW_KEYCLOAK_CLIENT_SECRET`, **and** substituted into `VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER` in the rendered realm | Airflow OAuth config + Keycloak's `airflow` client -- both sides must match |
| `api-secret-key` | `apiSecretKeySecretName` -> env `AIRFLOW__API__SECRET_KEY` | Airflow API server |
| `fernet-key` | `fernetKeySecretName` -> env `AIRFLOW__CORE__FERNET_KEY` | Every Airflow component, plus this chart's own sync-roles hook Job |
| `metadata-db-password` | `postgresql.auth.existingSecret` (by reference) | The postgres StatefulSet, and `make db-failover`/`db-failback` |
| `connection` | `data.metadataSecretName` -> env `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | Every Airflow component, plus this chart's own sync-roles hook Job. The full DSN, assembled in `vault/seed-secrets.sh`. The name is the chart's, not ours -- it looks this key up by that exact string |
| `replication-password` | `postgresql.auth.existingSecret` (by reference) | Streaming replication between primary and the two read replicas |
| `minio-root-user` | env `MINIO_ROOT_USER` via `secretKeyRef` | `minio/minio.yaml` (server + bucket Job) |
| `minio-root-password` | env `MINIO_ROOT_PASSWORD` via `secretKeyRef` | same |
| `minio-logging-conn` | env `AIRFLOW_CONN_MINIO_S3` | Airflow remote logging (`remote_log_conn_id: minio_s3`) |

`minio-logging-conn` is a **string containing JSON**, not a nested object --
that is Airflow's env-var connection format. Its `login`/`password` must
equal `minio-root-user`/`minio-root-password`, `endpoint_url` is the
in-cluster MinIO Service, and `addressing_style: path` is required because
MinIO does not do virtual-host-style bucket addressing.

To write all five by hand (this is exactly what `vault/seed-secrets.sh`
does -- `kv put` replaces the whole secret, so every key goes in one call):

```bash
kubectl -n airflow exec deploy/airflow-vault -- vault kv put secret/airflow-platform/airflow \
  client-secret='airflow-local-dev-secret' \
  api-secret-key='airflow-local-dev-api-secret-key' \
  fernet-key='YWlyZmxvdy1sb2NhbC1kZXYtZmVybmV0LWtleS0zMmI=' \
  metadata-db-password='postgres' \
  connection='postgresql://postgres:postgres@airflow-postgresql-primary:5432/postgres?sslmode=disable' \
  replication-password='replication-local-dev' \
  minio-root-user='airflow-logs' \
  minio-root-password='airflow-logs-local-dev-secret' \
  minio-logging-conn='{"conn_type":"aws","login":"airflow-logs","password":"airflow-logs-local-dev-secret","extra":{"endpoint_url":"http://airflow-minio:9000","region_name":"us-east-1","config_kwargs":{"s3":{"addressing_style":"path"}}}}'
```

Then `vault/sync-secrets.sh` (or `make vault`) to push them into the
`vault-airflow-secrets` Kubernetes Secret and re-render the realm file.

Vault runs in dev mode: in-memory storage, auto-unsealed, with a `secret/`
KV v2 mount created for free -- there's nothing here worth persisting across
restarts, so `make vault` always re-seeds and re-syncs from scratch (same
spirit as `make sso` always re-importing the realm). `VAULT_DEV_ROOT_TOKEN_ID`
in `vault/vault.yaml` is the one credential that structurally can't live
inside Vault itself, since it's what authenticates to Vault in the first
place. Nothing automated needs it over the network -- the Makefile talks to
Vault via `kubectl exec` into its pod (see `vault/seed-secrets.sh`) -- but
the Service is still exposed as a NodePort at http://localhost:8200 (see
`kind-config.yaml`'s third `extraPortMapping`), same as Keycloak's console,
purely so you can browse the Vault UI directly.

To change a secret value: edit `vault/seed-secrets.sh`, then `make vault` (or
`make sso`/`make deploy`, which both depend on it).

### The Fernet key

`fernet-key` is the one entry here that is **not** interchangeable with a
fresh random string. It encrypts Connection passwords and sensitive
Variables in the metadata DB, so **changing it makes everything already
encrypted undecryptable** (`InvalidToken`) -- unlike `api-secret-key`, where
rotating only forces everyone to log in again.

It must be 32 bytes, url-safe-base64-encoded; an arbitrary string like the
other literals here would be rejected. This repo's value decodes to the
readable `airflow-local-dev-fernet-key-32b` so it still reads as an obvious
local-dev value. Generate a real one with:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

To rotate one that already has encrypted data behind it, set
`AIRFLOW__CORE__FERNET_KEY="<new>,<old>"` (new first, old still able to
decrypt), re-encrypt, then drop the old one -- do not edit it in place.

Left unset, the chart would render its own `<release>-fernet-key` Secret
with a `randAlphaNum 32 | b64enc` value. That is already stable across
upgrades -- its template is a `pre-install` hook, so it is generated once --
so sourcing it from Vault is not about idempotency the way
`apiSecretKeySecretName` is; it is about the value living with the rest and
being knowable rather than a random string only the cluster has ever seen.

Two things follow from the chart only letting you name the Secret, not the
key inside it (the key is hardcoded as `fernet-key`):

* `vault/seed-secrets.sh` must use exactly that key name; and
* `chart/templates/sync-roles-job.yaml` reads the same value, so it follows
  `airflow.fernetKeySecretName` too rather than hardcoding
  `<release>-fernet-key`.

On an install that predates this, the chart's old `airflow-fernet-key`
Secret lingers unused -- hook resources are not part of the release
manifest, so `helm upgrade` does not garbage-collect it. Deleting it is safe
once every component reads the value from `vault-airflow-secrets`.

### The metadata-database credentials

Two keys, both pure Secret references -- no database credential reaches Helm
as a value:

```yaml
postgresql:
  auth:
    existingSecret: "vault-airflow-secrets"
    secretKeys:
      adminPasswordKey: "metadata-db-password"
      replicationPasswordKey: "replication-password"
data:
  metadataSecretName: "vault-airflow-secrets"
```

`secretKeys` is what makes the first one work against a Secret not designed
for it -- bitnami looks for `postgres-password` / `replication-password` by
default, and this remaps the lookups onto our own key names. With it set,
the subchart stops rendering its own `airflow-postgresql` Secret and both
StatefulSets read `vault-airflow-secrets` directly.

`data.metadataSecretName` covers the other side: Airflow's own DSN, under the
key `connection` (the name the chart looks for). The DSN is assembled in
`vault/seed-secrets.sh` from the password plus the host/port/db, so those
never have to be repeated in `chart/values.yaml`.

This is only possible because there is **no PgBouncer** (see
[Metadata database](#metadata-database)). The chart builds PgBouncer's
`users.txt` from the *literal* Helm value `data.metadataConnection.pass`,
with no Secret-reference equivalent -- so with PgBouncer enabled that
password has to reach Helm as a value no matter where it is stored, which
means a generated values file, a Helm plugin, or taking ownership of
`pgbouncer.ini` via `pgbouncer.configSecretName`. Dropping the pooler
removes the problem instead of working around it.

**Rotating is not a matter of editing the value.** `bitnami/postgresql`
applies the password only at *first* init: changing it against an existing
PVC leaves the running database on the old password, and the next deploy
simply breaks authentication. To rotate for real, `ALTER USER` inside the
running primary first, or delete the postgresql PVCs and let it re-init
(which destroys the metadata DB).

### Adding a new secret

Everything lives in the single Vault path `secret/airflow-platform/airflow`
as one more key. Adding one touches three files, in this order:

1. **`vault/seed-secrets.sh`** -- add the key to the `vault kv put`, and to
   the `echo` at the bottom:

   ```bash
   "${KUBECTL[@]}" exec deploy/airflow-vault -- vault kv put secret/airflow-platform/airflow \
     client-secret="airflow-local-dev-secret" \
     ...
     my-new-key="some-local-dev-value" >/dev/null
   ```

   `vault kv put` **replaces the whole secret**, so every key must be listed
   in that one command -- a second `put` with just the new key wipes the
   others.

2. **`vault/sync-secrets.sh`** -- read it back and add it to the Kubernetes
   Secret:

   ```bash
   MY_NEW=$(get my-new-key)
   ...
   "${KUBECTL[@]}" create secret generic vault-airflow-secrets \
     ...
     --from-literal=my-new-key="$MY_NEW" \
   ```

3. **Whatever consumes it.** Pick one:
   - an **env var on every Airflow container** -- add to
     `airflow.secret:` in `chart/values.yaml`:
     ```yaml
     - envName: "MY_NEW_ENV"
       secretName: "vault-airflow-secrets"
       secretKey: "my-new-key"
     ```
     An **Airflow connection** is just this with the env var named
     `AIRFLOW_CONN_<CONN_ID>` and the value a connection URI or JSON (that
     is how `minio_s3` works -- see `minio-logging-conn`). Such connections
     resolve everywhere but do **not** appear in the UI's Connections list,
     which only shows connections stored in the metadata DB.
   - a **`secretKeyRef` in a plain manifest** (`sso/keycloak.yaml`,
     `minio/minio.yaml`, ...) -- see MinIO's `minio-root-user`.
   - a **placeholder substituted into a rendered file**, for consumers that
     have no `secretKeyRef` equivalent -- see Keycloak's
     `VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER`. Add the `sed -e` to
     `vault/sync-secrets.sh`.

Then `make vault` (Vault is dev-mode/in-memory, so it re-seeds from scratch
on every run) and `make deploy` if step 3 changed the chart. Verify with:

```
kubectl -n airflow get secret vault-airflow-secrets -o jsonpath='{.data}' | python3 -m json.tool
kubectl -n airflow exec deploy/airflow-vault -- vault kv get secret/airflow-platform/airflow
```

## Files

| File                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `kind-config.yaml`          | Single-node kind cluster; NodePorts `30080`/`30081`/`30082` -> host `8080`/`8181`/`8200` |
| `Dockerfile`                | CVE-hardened image; bakes in `dags/`                                 |
| `Makefile`                  | Deployment targets; source of truth for the image and version pins   |
| `dags/`                     | One folder per project (`demo/`, `project1/`, `project2/`), each a self-contained Python package -- see [Projects under `dags/`](#projects-under-dags) |
| `dags/demo/`                | The demo project: three per-team DAGs (each with `access_control`), `hello_{small,medium,large,kubernetes}.py` (one per worker-class / K8s-pod placement), and `always_fails.py` |
| `dags/<project>/common/`    | That project's OWN shared helpers (`from <project>.common.greetings import ...`); the import doubles as a check that the package ships in the image. Projects never import one another's `common/` |
| `dags/project1/`, `dags/project2/` | Scaffold projects: one pipeline + one role each, showing the shape a new team folder takes |
| `tests/`                    | `pytest` unit tests for the DAGs; sits beside `dags/`, so the image never carries them -- see [Testing the DAGs](#testing-the-dags) |
| `sso/realm-airflow.json`    | Keycloak realm: 3 groups, 4 users, the `airflow` OIDC client -- carries a `VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER` token, filled in by `vault/sync-secrets.sh`; user passwords stay literal |
| `sso/keycloak.yaml`         | Keycloak Deployment + Service; admin login stays a literal local-dev value |
| `vault/vault.yaml`          | Dev-mode Vault Deployment + Service                                   |
| `vault/seed-secrets.sh`     | Single source of truth for this repo's Airflow-side secret values; pushes them into Vault |
| `vault/sync-secrets.sh`     | Reads secrets back out of Vault into Kubernetes Secrets and the rendered realm JSON |
| `minio/minio.yaml`          | Dev-mode MinIO Deployment + Service + log-bucket Job; S3 backend for Airflow remote task logging (lets the workers be stateless Deployments) |
| `postgres/failover.sh`      | Manual (break-glass) metadata-DB failover: fence the old primary, promote the freshest read replica, repoint the primary Service at it |
| `postgres/failback.sh`      | Rebuild a clean primary + replicas after a failover, carrying the data over -- required before the next `make deploy` |
| `chart/`                    | This repo's own umbrella Helm chart -- deploys `airflow` (a dependency, pinned in `chart/Chart.yaml`) as one Helm release together with this chart's own templates |
| `chart/Chart.yaml`          | Declares the `airflow` chart dependency (OCI mirror, pinned version) |
| `chart/Chart.lock`          | Pins the resolved dependency digest; committed like a lockfile        |
| `chart/values.yaml`         | Overrides for the `airflow` dependency (under the `airflow:` key): NodePort, api secret sourced from Vault (`apiSecretKeySecretName`), Keycloak sidecar, and the Flask-AppBuilder/Keycloak SSO config (`apiServer.apiServerConfig` / `webserver.webserverConfig`); also `image:` for this chart's own hook Job |
| `chart/templates/sync-roles-job.yaml` | Post-install/post-upgrade hook Job that creates the team roles and applies each DAG's `access_control` |
| `chart/templates/team-roles-configmap.yaml` | Ships every `chart/files/roles/*.json` into the cluster (one ConfigMap key per project) for the hook Job to read |
| `chart/files/roles/`        | One role file per project (`demo.json`, `project1.json`, `project2.json`), imported by `airflow roles import` and reconciled as their union |
| `chart/files/reconcile_roles.py` | Gap-free reconcile of the merged role files against the live DB (delta only, add-before-delete, refuses FAB built-ins) |

## Targets

| Target              | Description                                                        |
|---------------------|---------------------------------------------------------------------|
| `make up`           | Everything: cluster, Keycloak, Airflow + permissions (default)       |
| `make cluster`      | Create the kind cluster only                                         |
| `make vault`        | Deploy dev-mode Vault, seed it, and sync secrets into Kubernetes Secrets + the rendered realm file |
| `make minio`        | Deploy dev-mode MinIO (Airflow remote task logging) and (re)create the log bucket |
| `make db-failover`  | Manually fail the metadata DB over to the freshest read replica (break-glass) |
| `make db-failback`  | Rebuild a clean primary + replicas after a failover (run before the next `make deploy`) |
| `make sso`          | Deploy Keycloak and (re-)import the realm                            |
| `make build`        | Build the CVE-hardened Airflow image                                 |
| `make load`         | Build the image and load it into the kind cluster                    |
| `make dep-build`    | Fetch the `airflow` chart dependency into `chart/charts/`             |
| `make deploy`       | Build, load, and install/upgrade `chart/` via Helm (one release: Airflow + the team-roles-job hook, which creates team roles and applies each DAG's `access_control`) |
| `make test`         | Run the `dags/` unit tests (`tests/`) inside the hardened image      |
| `make status`       | Show pod status                                                      |
| `make logs`         | Tail scheduler logs                                                  |
| `make ui`           | Print the UI URLs                                                    |
| `make whoami`       | Show which cluster the targets will act on                           |
| `make clean`        | Uninstall Airflow and delete the kind cluster                        |
| `make down`         | Alias for `make clean`                                               |
| `make cluster-down` | Delete the kind cluster only                                         |
| `make push`         | Push the hardened image to the registry (manual, not part of `up`)   |
| `make chart-pull`   | Pull the upstream chart package (for mirroring)                      |
| `make chart-push`   | Mirror the chart to Docker Hub as an OCI artifact (manual)           |

Airflow runs `CeleryExecutor` with the chart's bundled Postgres and Redis
subcharts (both enabled by default) -- no external dependencies required.

Every `kubectl` and `helm` call is pinned to the `kind-airflow` context. Without
that, running `make up` against an already-existing cluster while your
current-context pointed elsewhere would deploy Airflow to that other cluster.
`make whoami` prints what the targets will act on.

## Projects under `dags/`

`dags/` is not a flat pile of files -- it holds one folder per project, and
each folder is a self-contained Python package:

```
dags/
  demo/                     # __init__.py -> importable as `demo`
    common/                 # demo's OWN shared helpers
      __init__.py
      greetings.py
    team_a_pipeline.py      # from demo.common.greetings import where
    ...
  project1/
    common/greetings.py     # project1's OWN copy -- independent of demo's
    project1_pipeline.py    # from project1.common.greetings import where
  project2/
    ...
```

`dags/` itself is on `sys.path` (the dag processor puts it there), and every
project folder has an `__init__.py`, so imports are **project-prefixed**:
`from project1.common.greetings import ...`. That prefix is what keeps two
projects' `common/` packages from colliding -- they are genuinely different
modules (`demo.common` vs `project1.common`), and a project may change or
delete its own `common/` without touching any other.

The `import` also doubles as a liveness check: every pipeline imports its
project's `common`, so if that package went missing from the image or broke,
each importer would surface in `airflow dags list-import-errors` rather than
failing silently at run time. Keep non-DAG modules under `common/` (or
another subpackage), never loose in a project folder -- the processor parses
every top-level `.py` there looking for DAG objects.

### Adding or changing a DAG

DAGs ship inside the image, so there is no DAG volume, no gitSync, and nothing
to mount:

1. Add or edit a file under `dags/<project>/`, with an `access_control` entry
   naming a role defined in `chart/files/roles/<project>.json`.
2. Update that project's manifest at `tests/test_<project>/manifest.py`
   (`EXPECTED_DAG_IDS`, and `TEAM_DAG_ROLE` / `QUEUE_DAG_CLASS` /
   `NO_ACL_DAG_IDS` as applicable) -- the tests assert against it.
3. `make up` (or `make deploy`).

A DAG with no `access_control` is visible to nobody but `Admin`, since no
team role holds the global `DAGs` permission.

### Adding a project

1. `dags/<project>/__init__.py` + `dags/<project>/common/__init__.py` +
   `common/greetings.py` (copy an existing one).
2. One or more pipeline files, importing `from <project>.common... import`.
3. `chart/files/roles/<project>.json` -- the role(s) that project's DAGs
   grant. The chart auto-globs `files/roles/*.json`; no template edit.
4. `tests/test_<project>/` -- `__init__.py`, `manifest.py`, and copy
   `test_dags.py` + `test_greetings.py` from another project (they are
   generic -- `test_dags.py` is byte-identical everywhere, driven by
   `manifest.py`).

`tests/test_projects_global.py` fails if a `dags/<project>/` has no matching
`tests/test_<project>/manifest.py`, so a half-added project can't slip
through.

## Testing the DAGs

`tests/` holds the `dags/` unit tests. It sits at the repo root next to
`dags/`, not inside it, so the `Dockerfile`'s `COPY dags/` never picks them
up: they neither ship to the cluster nor get parsed by the dag processor.

The suite is a **unit test of the DAGs**: it reads only `dags/` and each
project's `tests/test_<project>/manifest.py`, never the Helm chart. Keeping
the chart in step with the DAGs (a role in `chart/files/roles/<project>.json`
for every role a DAG grants, a worker set in `chart/values.yaml` for every
`queue=`) is a deploy concern -- the sync-roles hook and the `make up` smoke
run cover it.

Its layout mirrors `dags/`: one `tests/test_<project>/` package per project,
each with a `manifest.py` (exactly what that project ships) and thin test
files. Only three files sit at the top:

- **`conftest.py`** -- the bootstrap (env setup + the session `DagBag`
  fixtures) *and* the shared pure-Python helpers (project discovery,
  `dags_in_project`, `access_control` flattening); test files import them
  with `from tests.conftest import ...`.
- **`__init__.py`** -- empty; makes `tests/` a package so those imports and
  the per-project `from . import manifest` resolve.
- **`test_projects_global.py`** -- cross-project invariants: every
  `dags/<project>/` has a matching `tests/test_<project>/manifest.py`, and
  the manifests account for every parsed DAG with no `dag_id` claimed twice.

Per project, `test_dags.py` (byte-identical everywhere, driven by that
project's `manifest.py`) covers: `DagBag` parses with zero import errors
(which also proves that project's `common/` ships and imports), the DAG set
matches `EXPECTED_DAG_IDS` one-per-source-file, each `TEAM_DAG_ROLE` DAG
grants exactly its own role `{can_read, can_edit}` (read straight off the
DAG's `access_control`), and each `NO_ACL_DAG_IDS` DAG carries no
`access_control` (Admin-only) -- the isolation contract from
[How the isolation actually works](#how-the-isolation-actually-works) turned
into a regression guard. The `demo` project adds `test_dag_behavior.py`
(`extract -> report` wiring, `always_fails` raises with `retries: 0`) and
`test_worker_placement.py` (each `hello_*` task pins its expected `queue=`,
`hello_kubernetes` runs as its own pod via `executor_config['pod_override']`).
Every project has a `test_greetings.py` -- pure unit tests for its own
`common.greetings`, no Airflow needed.

Run them the easy way -- inside the hardened image, which already has
Airflow 3.3.1 and the DAGs:

```
make test
```

Or locally against a matching Airflow (pin it to `AIRFLOW_VERSION`) for the
full suite:

```
pip install -r tests/requirements.txt \
  -c "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.10.txt"
pytest
```

Or with **no container and no Airflow** at all -- the `dagbag` fixture and
everything downstream of it is skipped rather than erroring, so this still
runs the per-project `common.greetings` unit tests and the `dags/` <->
`tests/` layout guard:

```
pip install 'pytest>=8,<9'
pytest
```

## Metadata database

The chart's bundled `postgresql` subchart runs in **replication** mode --
1 primary + 2 read replicas, streaming replication. Every Airflow component
connects **directly** to the primary Service; there is no connection pooler
(`airflow.postgresql` / `airflow.pgbouncer` in `chart/values.yaml`):

```
Airflow (scheduler, workers, api-server, ...)
                     |
         airflow-postgresql-primary  (Service)
                     |
      airflow-postgresql-primary-0   (writable)
             |                    |
airflow-postgresql-read-0   airflow-postgresql-read-1
```

The replicas are for **failover only** -- Airflow is write-heavy and does
not route reads to standbys, so they carry no query load.

### No connection pooler

`airflow.pgbouncer.enabled` is `false`, which is a deliberate trade-off in
both directions.

**What it costs.** Airflow opens a connection per scheduler, per worker
process, per triggerer, per dag-processor, **and per running task** -- and
with nothing pooling in front, all of them land on Postgres directly.
`max_connections` is the ceiling that gets hit first, so it is raised from
the stock 100 -- on the primary **and on the read replicas**:

```yaml
extendedConfiguration: |
  max_connections = 500
```

The replicas need it too because a replica is a promotion target: after
`pg_promote` it *is* the primary, and leaving it at 100 would mean
surviving the failover only to exhaust connections minutes later, with no
way to reconfigure it mid-incident without another restart.

Postgres forks a process per connection (~5-10MB each), so this is also a
memory budget -- 500 x ~8MB is roughly 4Gi worst case, which is what the
`resources.limits.memory` on both StatefulSets is sized for. Raising
`max_connections` without raising that just moves the failure from "too
many clients" to an OOMKill. Memory limits but no CPU limits, matching the
worker classes: a CPU limit only buys throttling, and the database is the
one thing here that should never be throttled.

Size all of this against real worker concurrency -- roughly
`(workers x worker_concurrency) + ~15` for the always-on components -- not
against this repo's demo numbers. If you push concurrency up, these are the
first things to revisit.

**What it buys.** The metadata credential becomes a pure Secret reference.
The chart renders PgBouncer's `users.txt` from the *literal* Helm value
`data.metadataConnection.pass`, and there is no values key pointing that at
a Secret -- so with PgBouncer enabled the password must reach Helm as a
value, whatever it is stored in. Keeping it out of tracked YAML then needs
a generated values file, a Helm plugin, or taking ownership of the whole
`pgbouncer.ini` through `pgbouncer.configSecretName`. Every one of those is
machinery in the deploy path. Dropping the pooler removes the problem
rather than working around it, and `data.metadataSecretName` then covers
the whole DSN in one reference -- see
[The metadata-database credentials](#the-metadata-database-credentials).

To put a pooler back, set `pgbouncer.enabled: true` and be ready to supply
`data.metadataConnection.pass` as a Helm value again.

### Failover and failback runbook

`bitnami/postgresql` is **not** an HA chart: the replicas are plain
streaming standbys and nothing promotes one automatically. There is no
detection either, so the RTO is however long it takes a human to notice.
The whole cycle below was exercised on a live cluster, primary hard-killed.

```
 healthy    -- primary-0 (RW) --> read-0, read-1 (RO)
     |
 primary dies                              <- nothing detects this
     |
 make db-failover      (~1-2 min)
     |
 degraded   -- read-1 (RW), no replicas    <- Airflow fine, do NOT deploy
     |
 make db-failback      (~5 min, rebuilds)
     |
 healthy    -- primary-0 (RW) --> read-0, read-1 (RO)
```

#### 1. Failover -- during the incident

**When:** the primary is gone. Airflow cannot reach the database and
`airflow-postgresql-primary-0` is not `Running` (or is unreachable).

```
make db-failover        # postgres/failover.sh
```

| # | Step | Why |
|---|------|-----|
| 1 | **Fence the old primary** -- scale its StatefulSet to 0, wait for the pod to go | `pg_promote` does **not** stop the old primary. Skip this and you get a real split brain: verified here, the old primary kept accepting `INSERT`s the promoted node never saw, while the other replica went on streaming from it |
| 2 | **Pick the target** -- compare `pg_last_wal_replay_lsn()` across the `read-*` pods, take the highest | Least data loss |
| 3 | **Promote** -- `pg_promote(wait => true)`, poll until `pg_is_in_recovery() = f` | Makes it genuinely writable |
| 4 | **Repoint the Service selector** -- `airflow-postgresql-primary` -> that pod | Every component connects to that Service by name, so **Airflow's connection string never changes** (the DSN in Vault keeps pointing at `airflow-postgresql-primary`) |
| 5 | **Restart the Airflow tier** | Drops stale connections now instead of waiting for `pool_pre_ping` |

Options: `TARGET=airflow-postgresql-read-0` to force a specific replica;
`FENCE=false` to skip fencing (**unsafe** -- only when the old primary is
provably gone).

Verify:

```
kubectl -n airflow get endpoints airflow-postgresql-primary   # -> the promoted pod
kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- airflow db check
```

You are now on **one writable node with no replicas**, and the next
`make deploy` would cause an outage -- see below.

#### 2. Failback -- as soon as practical

**When:** failover is done and Airflow is serving. **Must happen before the
next `make deploy`.**

```
make db-failback        # postgres/failback.sh
```

| # | Step |
|---|------|
| 1 | Find the one pod with `pg_is_in_recovery() = f` |
| 2 | `pg_dump --clean --if-exists` it to a local file (**aborts if the dump is empty**, so it never destroys a cluster it failed to read) |
| 3 | Reset the Service selector to the chart's own labels (`patch --type json` **replaces** the map rather than merging) |
| 4 | Delete both postgres StatefulSets and their PVCs -- the diverged timelines are unrecoverable without `pg_rewind` |
| 5 | `helm upgrade` recreates a clean primary + 2 replicas |
| 6 | Restore the dump into the new `primary-0` |
| 7 | Restart the Airflow tier |

If it dies partway (after step 4 there is no writable node left to dump
from), re-run pointing at the dump it already took:

```
DUMP=/tmp/airflow-failback-XXXX.sql make db-failback
```

Verify:

```
kubectl -n airflow get endpoints airflow-postgresql-primary   # -> airflow-postgresql-primary-0
kubectl -n airflow exec airflow-postgresql-primary-0 -c postgresql -- \
  env PGPASSWORD=postgres psql -qtAX -U postgres -c "SELECT client_addr,state FROM pg_stat_replication;"
  # two rows, both streaming
```

#### Why failback is not optional

After a failover the cluster is not merely degraded, it is
**booby-trapped**. The chart still believes `airflow-postgresql-primary-0`
is the primary, so the next `helm upgrade` -- i.e. any `make deploy` --
will:

* **merge** its own selector back into the primary Service (Kubernetes does
  not replace it), leaving a selector that demands both `component=primary`
  *and* `pod-name=<promoted replica>`, which matches nothing -- the Service
  ends up with **zero endpoints**; and
* scale the fenced StatefulSet back to 1, starting a stale `primary-0` that
  CrashLoopBackOffs on `could not locate a valid checkpoint record`.

With PgBouncer in front this used to be *latent* -- it held already
established server connections, so `airflow db check` still passed right
after the upgrade and the failure only surfaced on the next PgBouncer
restart, which was much harder to diagnose. Without a pooler the breakage
is immediate instead: the Service has no endpoints, so the next connection
from any component fails outright. Louder, and easier to attribute. (The
latent behaviour was reproduced here before the pooler was removed.)

So: does the primary have to go back to being the primary? **Yes** -- not
for correctness (the promoted node is a real primary and Airflow is happy
pointing at it), but because there is no redundancy until you rebuild, and
because leaving it turns the next routine deploy into an outage.

For anything beyond a POC, use a database that fails over on its own:
managed (RDS Multi-AZ / Cloud SQL HA / Azure Flexible Server zone-redundant)
or, on-prem, an operator (CloudNativePG, Crunchy PGO) or Patroni + etcd.
Point `airflow.postgresql.enabled: false` and
`airflow.data.metadataSecretName` at it.

## Worker classes and per-DAG Kubernetes pods

The executor is `CeleryExecutor,KubernetesExecutor` (Airflow 3 multi-executor).
Two ways to give a DAG more CPU/memory:

**Fixed classes (Celery).** Three worker `Deployment`s, one per size, each
consuming its own queue -- one entry per class in `chart/values.yaml` under
`airflow.workers.celery.sets`:

| Class    | Queue    | Deployment                | Default for |
|----------|----------|---------------------------|-------------|
| small    | `small`  | `airflow-worker-small`    | any task with no `queue` (`operators.default_queue`) |
| medium   | `medium` | `airflow-worker-medium`   | — |
| large    | `large`  | `airflow-worker-large`    | — |

Route to one with `queue=`:

```python
with DAG("my_pipeline", default_args={"queue": "medium"}, ...):   # whole DAG
    ...

@task(queue="large")                                              # one task
def heavy(): ...
```

Resource values in `values.yaml` are starting points -- size them for your
nodes. Add a class by appending to `sets:`; each entry also gets its own KEDA
scaler if `workers.celery.keda` is enabled.

**One-off pod (KubernetesExecutor).** For a task whose needs don't fit a
class, run it as its own pod and size it inline:

```python
from kubernetes.client import models as k8s

@task(
    executor="KubernetesExecutor",
    executor_config={"pod_override": k8s.V1Pod(spec=k8s.V1PodSpec(containers=[
        k8s.V1Container(name="base", resources=k8s.V1ResourceRequirements(
            requests={"cpu": "2", "memory": "8Gi"}, limits={"memory": "8Gi"}))]))},
)
def massive(): ...
```

`dags/hello_small.py`, `hello_medium.py`, `hello_large.py` and
`hello_kubernetes.py` are one hello-world DAG per placement.

### Stateless workers + remote logging

The workers are plain `Deployment`s (`airflow.workers.persistence.enabled:
false`), not `StatefulSet`s with a per-pod log PVC. That only works because
task logs go to **MinIO** instead of the worker's local disk:
`airflow.config.logging` sets `remote_logging` + `remote_base_log_folder:
s3://airflow-logs`, and the connection `minio_s3` (`AIRFLOW_CONN_MINIO_S3`)
is a JSON connection built in `vault/seed-secrets.sh` -- `endpoint_url` at
the in-cluster `airflow-minio` Service, path-style addressing (MinIO needs
it), creds from the same Vault secret.

`make minio` deploys a dev-mode MinIO (`minio/minio.yaml`, single replica,
`emptyDir`) and re-creates the `airflow-logs` bucket every run. `make
deploy` depends on it. Console: `kubectl -n airflow port-forward
svc/airflow-minio 9001:9001`, then `http://localhost:9001` with the
`minio-root-user` / `minio-root-password` values from `vault/seed-secrets.sh`.

A KubernetesExecutor task pod (see above) keeps its logs the same way --
they land in MinIO after the pod is deleted.

## Changing SSO users or groups

1. Edit `sso/realm-airflow.json`.
2. `make sso` -- the realm ships as a ConfigMap and the target restarts Keycloak
   so the change is re-imported.
3. New groups also need an `AUTH_ROLES_MAPPING` entry in the
   `webserver_config.py` embedded in `chart/values.yaml` and a role in the
   relevant `chart/files/roles/<project>.json`, then `make deploy`.

## Updating the image

`IMAGE_REPO` / `IMAGE_TAG` in the Makefile are the single source of truth: the
`docker build` tag, the `kind load` tag, the sidecar image, and the
`defaultAirflowRepository` / `defaultAirflowTag` / this chart's own top-level
`image.*` (for the team-roles-job hook) that Helm renders into the pod specs
all derive from them. So picking up a new CVE fix is a one-line change:

1. Edit the `Dockerfile`.
2. Bump the revision suffix in `IMAGE_TAG` (`3.3.1-hardened.1` -> `.2`).
3. `make up`

Don't hardcode an image, version, or tag directly in `chart/values.yaml` --
those fields are placeholder tokens (`IMAGE_REPO_PLACEHOLDER`,
`IMAGE_TAG_PLACEHOLDER`, `AIRFLOW_VERSION_PLACEHOLDER`,
`PLACEHOLDER_SET_FROM_MAKEFILE`), substituted by `make deploy`'s `sed` pass
into `chart/.values.rendered.yaml`. A literal value there would only be used
by someone bypassing the Makefile and calling `helm upgrade` directly --
`make deploy` always overwrites it with the real value on every run.

Note that `apt-get upgrade` in the `Dockerfile` makes builds deliberately
non-reproducible: the same tag rebuilt weeks later can contain different
packages. Bump `IMAGE_TAG` when you need one rebuild told apart from another.

## Updating the chart mirror

`make deploy` installs the `airflow` dependency from the Docker Hub OCI
mirror, not the upstream chart repo, so it doesn't depend on
`https://airflow.apache.org` being reachable. To pick up a new chart version:

1. Bump `CHART_VERSION` in the Makefile.
2. `helm registry login registry-1.docker.io -u isliao613`
3. `make chart-push`
4. Bump the matching `version:` under `dependencies:` in `chart/Chart.yaml`.
5. `make dep-build` (or just `make deploy`, which runs it) to refetch into
   `chart/charts/` and update `chart/Chart.lock`.

## Credentials

Every credential in this repo is a hardcoded local-development value: the
Keycloak admin, the four demo users (including `admin`/`admin` for Airflow),
the OIDC client secret, the API secret key, and the MinIO root user /
password. They exist so `make up` needs no setup. Replace all of them before
this is reachable by anyone but you.

The OIDC client secret, the API secret key, and the MinIO credentials --
what Airflow itself actually needs to function -- live in Vault
(`vault/seed-secrets.sh`; see [Secrets in Vault](#secrets-in-vault)) rather
than as literals in `chart/values.yaml`/`sso/realm-airflow.json`/
`minio/minio.yaml`. The Keycloak admin login and
the four demo users' passwords are human login credentials, not something
Airflow's backend consumes, so they stay plain literals in
`sso/keycloak.yaml` and `sso/realm-airflow.json`.

Vault's own dev-mode root token (`VAULT_DEV_ROOT_TOKEN_ID` in
`vault/vault.yaml`) can't live inside Vault itself since it's what
bootstraps access to Vault in the first place -- see
[Secrets in Vault](#secrets-in-vault).

## Cleanup

```
make clean
```
