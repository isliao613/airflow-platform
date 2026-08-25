# airflow-platform

One-click local deployment of Apache Airflow 3.3.0 (Helm chart 1.22.0) on a
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
`airflow` realm (rendered from those Vault-backed secrets), builds the
CVE-hardened Airflow image from the `Dockerfile`, loads it into the cluster
with `kind load` (no registry push needed), and installs `chart/` -- this
repo's own umbrella Helm chart, which wraps the `apache-airflow/airflow`
chart (pinned to `1.22.0`, from a Docker Hub OCI mirror) as a dependency,
plus its own `templates/sync-team-roles-job.yaml` -- a post-install/
post-upgrade hook Job that creates the team roles and applies each DAG's
`access_control` once the release installs.

The image build is the slowest step and the one most likely to fail first: it
pulls the `apache/airflow:3.3.0` base image, applies OS updates, and installs a
patched `litellm`. What gets deployed is that locally built
`isliao613/airflow:3.3.0-hardened.1`, **not** upstream `apache/airflow:3.3.0`
directly -- see `Dockerfile` for what is patched and why.

| Service          | URL                     | Credentials                       |
|------------------|-------------------------|-----------------------------------|
| Airflow UI       | http://localhost:8080   | "Sign in with keycloak"           |
| Keycloak console | http://localhost:8181   | `admin` / `admin`                 |

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
3. **Team roles hold no global DAG permission.** `chart/files/roles.json`
   gives each team role the built-in Viewer permissions **minus** `can_read`
   on the
   global `DAGs` resource. That single omission is the whole mechanism:
   `FabAuthManager._is_authorized_dag()` short-circuits to "allow everything"
   for anyone holding it.
4. **Each DAG grants itself to one role.** Every DAG file declares
   `access_control={"team_x": {"can_read", "can_edit"}}`, which
   `airflow sync-perm --include-dags` turns into a `DAG:<dag_id>` permission on
   that role. Listing still works, because Airflow also accepts any `can_read`
   on a `DAG:` resource as permission to list -- and then filters the list down
   to exactly those DAGs.

Steps 3 and 4 are done by `chart/templates/sync-team-roles-job.yaml`, a
post-install/post-upgrade hook Job defined directly in this repo's own
umbrella chart. It's installed as part of the same Helm release as the
airflow dependency (Helm merges hooks from a root chart and its dependencies
into one ordering for the release), so it can read that release's own
secrets (`airflow-metadata`, `airflow-fernet-key`) and `airflow.cfg`
(`airflow-config`, needed because that's where `auth_manager` is set)
directly via `.Release.Name` -- no separate config needed. It waits for the
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

`Admin` needs no entry in `chart/files/roles.json` -- it's built into FAB
already, with every permission on every resource. That's also the caveat:
unlike the team roles, `Admin` holds the global `DAGs` permission, so
`admin`/`admin` sees and can edit every team's DAG, and can manage Airflow's
users, roles, connections, and variables through the UI -- the one identity
in this realm that isn't scoped to a single team. Manage Keycloak identities
themselves (adding/removing users or groups) through the Keycloak console.

## Secrets in Vault

The secrets Airflow itself needs to function -- the OIDC client secret and
Airflow's API secret key -- live in a dev-mode Vault (`vault/vault.yaml`)
instead of being a literal value in tracked chart/SSO YAML.
`vault/seed-secrets.sh` is the single source of truth for the actual VALUES
(still hardcoded local-dev values, just centralized in one file instead of
scattered across two); `vault/sync-secrets.sh` reads them back out and:

- Creates two Kubernetes Secrets -- `vault-oidc-client-secret`,
  `vault-api-secret-key` -- consumed via the airflow chart's own
  `apiSecretKeySecretName` / top-level `secret:` list (`chart/values.yaml`),
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

Vault runs in dev mode: in-memory storage, auto-unsealed, with a `secret/`
KV v2 mount created for free -- there's nothing here worth persisting across
restarts, so `make vault` always re-seeds and re-syncs from scratch (same
spirit as `make sso` always re-importing the realm). `VAULT_DEV_ROOT_TOKEN_ID`
in `vault/vault.yaml` is the one credential that structurally can't live
inside Vault itself, since it's what authenticates to Vault in the first
place; the Makefile talks to Vault via `kubectl exec` into its pod (see
`vault/seed-secrets.sh`), not over the network, so nothing outside the
cluster needs it.

To change a secret value: edit `vault/seed-secrets.sh`, then `make vault` (or
`make sso`/`make deploy`, which both depend on it).

## Files

| File                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `kind-config.yaml`          | Single-node kind cluster; NodePorts `30080`/`30081` -> host `8080`/`8181` |
| `Dockerfile`                | CVE-hardened image; bakes in `dags/`                                 |
| `Makefile`                  | Deployment targets; source of truth for the image and version pins   |
| `dags/`                     | Three demo DAGs, one per team, each with `access_control`            |
| `sso/realm-airflow.json`    | Keycloak realm: 3 groups, 4 users, the `airflow` OIDC client -- carries a `VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER` token, filled in by `vault/sync-secrets.sh`; user passwords stay literal |
| `sso/keycloak.yaml`         | Keycloak Deployment + Service; admin login stays a literal local-dev value |
| `vault/vault.yaml`          | Dev-mode Vault Deployment + Service                                   |
| `vault/seed-secrets.sh`     | Single source of truth for this repo's Airflow-side secret values; pushes them into Vault |
| `vault/sync-secrets.sh`     | Reads secrets back out of Vault into Kubernetes Secrets and the rendered realm JSON |
| `chart/`                    | This repo's own umbrella Helm chart -- deploys `airflow` (a dependency, pinned in `chart/Chart.yaml`) as one Helm release together with this chart's own templates |
| `chart/Chart.yaml`          | Declares the `airflow` chart dependency (OCI mirror, pinned version) |
| `chart/Chart.lock`          | Pins the resolved dependency digest; committed like a lockfile        |
| `chart/values.yaml`         | Overrides for the `airflow` dependency (under the `airflow:` key): NodePort, api secret sourced from Vault (`apiSecretKeySecretName`), Keycloak sidecar, and the Flask-AppBuilder/Keycloak SSO config (`apiServer.apiServerConfig` / `webserver.webserverConfig`); also `image:` for this chart's own hook Job |
| `chart/templates/sync-team-roles-job.yaml` | Post-install/post-upgrade hook Job that creates the team roles and applies each DAG's `access_control` |
| `chart/templates/team-roles-configmap.yaml` | Ships `chart/files/roles.json` into the cluster for the hook Job to read |
| `chart/files/roles.json`    | The three team roles, imported by `airflow roles import`             |

## Targets

| Target              | Description                                                        |
|---------------------|---------------------------------------------------------------------|
| `make up`           | Everything: cluster, Keycloak, Airflow + permissions (default)       |
| `make cluster`      | Create the kind cluster only                                         |
| `make vault`        | Deploy dev-mode Vault, seed it, and sync secrets into Kubernetes Secrets + the rendered realm file |
| `make sso`          | Deploy Keycloak and (re-)import the realm                            |
| `make build`        | Build the CVE-hardened Airflow image                                 |
| `make load`         | Build the image and load it into the kind cluster                    |
| `make dep-build`    | Fetch the `airflow` chart dependency into `chart/charts/`             |
| `make deploy`       | Build, load, and install/upgrade `chart/` via Helm (one release: Airflow + the team-roles-job hook, which creates team roles and applies each DAG's `access_control`) |
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

## Adding or changing a DAG

DAGs ship inside the image, so there is no DAG volume, no gitSync, and nothing
to mount:

1. Add or edit a file in `dags/`, with an `access_control` entry naming a team
   role.
2. `make up` (or `make deploy`).

A DAG with no `access_control` is visible to nobody, since no team role holds
the global `DAGs` permission.

## Changing SSO users or groups

1. Edit `sso/realm-airflow.json`.
2. `make sso` -- the realm ships as a ConfigMap and the target restarts Keycloak
   so the change is re-imported.
3. New groups also need an `AUTH_ROLES_MAPPING` entry in the
   `webserver_config.py` embedded in `chart/values.yaml` and a role in
   `chart/files/roles.json`, then `make deploy`.

## Updating the image

`IMAGE_REPO` / `IMAGE_TAG` in the Makefile are the single source of truth: the
`docker build` tag, the `kind load` tag, the sidecar image, and the
`defaultAirflowRepository` / `defaultAirflowTag` / this chart's own top-level
`image.*` (for the team-roles-job hook) that Helm renders into the pod specs
all derive from them. So picking up a new CVE fix is a one-line change:

1. Edit the `Dockerfile`.
2. Bump the revision suffix in `IMAGE_TAG` (`3.3.0-hardened.1` -> `.2`).
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
the OIDC client secret, and the API secret key. They exist so `make up`
needs no setup. Replace all of them before this is reachable by anyone but
you.

The OIDC client secret and API secret key -- the two Airflow itself actually
needs to function -- live in Vault (`vault/seed-secrets.sh`; see
[Secrets in Vault](#secrets-in-vault)) rather than as literals in
`chart/values.yaml`/`sso/realm-airflow.json`. The Keycloak admin login and
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
