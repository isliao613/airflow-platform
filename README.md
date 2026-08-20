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

This creates the `airflow` kind cluster, deploys Keycloak and imports the
`airflow` realm, builds the CVE-hardened Airflow image from the `Dockerfile`,
loads it into the cluster with `kind load` (no registry push needed), installs
the `apache-airflow/airflow` Helm chart (pinned to `1.22.0`) from a Docker Hub
OCI mirror, and then creates the team roles and applies each DAG's
`access_control`.

The image build is the slowest step and the one most likely to fail first: it
pulls the `apache/airflow:3.3.0` base image, applies OS updates, and installs a
patched `litellm`. What gets deployed is that locally built
`isliao613/airflow:3.3.0-hardened.2`, **not** upstream `apache/airflow:3.3.0`
directly -- see `Dockerfile` for what is patched and why.

| Service          | URL                     | Credentials                       |
|------------------|-------------------------|-----------------------------------|
| Airflow UI       | http://localhost:8080   | "Sign in with keycloak"           |
| Keycloak console | http://localhost:8081   | `admin` / `admin`                 |

## SSO and per-team DAG isolation

Identities live in Keycloak, not in Airflow. Three groups map to three Airflow
roles, and each role can see exactly one DAG:

| Keycloak user | Password | Keycloak group    | Airflow role | Visible DAG        |
|---------------|----------|-------------------|--------------|--------------------|
| `alice`       | `alice`  | `airflow-team-a`  | `team_a`     | `team_a_pipeline`  |
| `bob`         | `bob`    | `airflow-team-b`  | `team_b`     | `team_b_pipeline`  |
| `carol`       | `carol`  | `airflow-team-c`  | `team_c`     | `team_c_pipeline`  |

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
2. **FAB maps groups to roles.** `AUTH_ROLES_MAPPING` in
   `airflow/webserver_config.py` turns `airflow-team-a` into the `team_a` role,
   and `AUTH_ROLES_SYNC_AT_LOGIN = True` re-applies it on every login -- so
   moving a user between groups in Keycloak takes effect on their next sign-in,
   with no action in Airflow.
3. **Team roles hold no global DAG permission.** `airflow/roles.json` gives
   each team role the built-in Viewer permissions **minus** `can_read` on the
   global `DAGs` resource. That single omission is the whole mechanism:
   `FabAuthManager._is_authorized_dag()` short-circuits to "allow everything"
   for anyone holding it.
4. **Each DAG grants itself to one role.** Every DAG file declares
   `access_control={"team_x": {"can_read", "can_edit"}}`, which
   `airflow sync-perm --include-dags` turns into a `DAG:<dag_id>` permission on
   that role. Listing still works, because Airflow also accepts any `can_read`
   on a `DAG:` resource as permission to list -- and then filters the list down
   to exactly those DAGs.

`make sso-perms` runs steps 3 and 4. It waits for the dag processor to
serialize the DAG files first, because `sync-perm` reads `access_control` from
the serialized DAGs in the database, not from the files on disk.

### Why both sides reach Keycloak at `localhost:8081`

OIDC tokens carry an issuer, and the browser and the Airflow API server have to
agree on it. They reach the same Keycloak by different routes:

- **Browser** -> host port 8081 -> kind `extraPortMapping` -> NodePort 30081
- **API server** -> a `socat` sidecar in its own pod listening on
  `127.0.0.1:8081`, forwarding to the `airflow-keycloak` Service

Both therefore use the literal URL `http://localhost:8081`, so the issuer
matches and no host-side `/etc/hosts` entry is required. The sidecar runs the
Airflow image itself (already in the cluster, with `socat` added by the
`Dockerfile`) rather than pulling a second image just to forward a port.

Changing the host port means changing it in three places: `kind-config.yaml`,
`KC_HOSTNAME` in `sso/keycloak.yaml`, and the sidecar in `values.yaml`.

### There is no Airflow admin

The three groups above are the only identities, by design, and none of them
maps to Airflow's `Admin` role -- so nobody can manage Airflow's users, roles,
connections, or variables through the UI. Manage identities in the Keycloak
console instead.

To add an admin, create a fourth Keycloak group and map it:

```python
# airflow/webserver_config.py
AUTH_ROLES_MAPPING = {
    "airflow-admins": ["Admin"],
    ...
}
```

`Admin` is a built-in role, so it needs no entry in `airflow/roles.json` --
but note it holds global `DAGs` permission and therefore sees every DAG.

## Files

| File                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `kind-config.yaml`          | Single-node kind cluster; NodePorts `30080`/`30081` -> host `8080`/`8081` |
| `Dockerfile`                | CVE-hardened image; bakes in `dags/` and the SSO config              |
| `values.yaml`               | Chart overrides: NodePort, pinned api secret, Keycloak sidecar       |
| `Makefile`                  | Deployment targets; source of truth for the image and version pins   |
| `dags/`                     | Three demo DAGs, one per team, each with `access_control`            |
| `sso/realm-airflow.json`    | Keycloak realm: 3 groups, 3 users, the `airflow` OIDC client         |
| `sso/keycloak.yaml`         | Keycloak Deployment + Service                                        |
| `airflow/webserver_config.py` | Flask-AppBuilder OAuth config (baked into the image)               |
| `airflow/roles.json`        | The three team roles, imported by `airflow roles import`             |

## Targets

| Target              | Description                                                        |
|---------------------|---------------------------------------------------------------------|
| `make up`           | Everything: cluster, Keycloak, Airflow, permissions (default)        |
| `make cluster`      | Create the kind cluster only                                         |
| `make sso`          | Deploy Keycloak and (re-)import the realm                            |
| `make build`        | Build the CVE-hardened Airflow image                                 |
| `make load`         | Build the image and load it into the kind cluster                    |
| `make deploy`       | Build, load, and install/upgrade Airflow via Helm                    |
| `make sso-perms`    | Create team roles and apply each DAG's `access_control`              |
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
2. `make up` (or `make deploy sso-perms`).

A DAG with no `access_control` is visible to nobody, since no team role holds
the global `DAGs` permission.

## Changing SSO users or groups

1. Edit `sso/realm-airflow.json`.
2. `make sso` -- the realm ships as a ConfigMap and the target restarts Keycloak
   so the change is re-imported.
3. New groups also need an `AUTH_ROLES_MAPPING` entry in
   `airflow/webserver_config.py` and a role in `airflow/roles.json`, then
   `make deploy sso-perms`.

## Updating the image

`IMAGE_REPO` / `IMAGE_TAG` in the Makefile are the single source of truth: the
`docker build` tag, the `kind load` tag, the sidecar image, and the
`defaultAirflowRepository` / `defaultAirflowTag` that Helm renders into the pod
spec all derive from them. So picking up a new CVE fix is a one-line change:

1. Edit the `Dockerfile`.
2. Bump the revision suffix in `IMAGE_TAG` (`3.3.0-hardened.2` -> `.3`).
3. `make up`

Don't hardcode the image in `values.yaml`. The Airflow image is overridden with
`--set` at deploy time, and the sidecar image is rendered from the placeholder
into `.values.rendered.yaml`, so a literal tag there would either be ignored or
silently overwritten while looking authoritative.

Note that `apt-get upgrade` in the `Dockerfile` makes builds deliberately
non-reproducible: the same tag rebuilt weeks later can contain different
packages. Bump `IMAGE_TAG` when you need one rebuild told apart from another.

## Updating the chart mirror

`make deploy` installs from the Docker Hub OCI mirror, not the upstream chart
repo, so it doesn't depend on `https://airflow.apache.org` being reachable.
To pick up a new chart version:

1. Bump `CHART_VERSION` in the Makefile.
2. `helm registry login registry-1.docker.io -u isliao613`
3. `make chart-push`

## Credentials

Every credential in this repo is a hardcoded local-development value: the
Keycloak admin, the three demo users, the OIDC client secret in
`sso/realm-airflow.json` and `airflow/webserver_config.py`, and `apiSecretKey`
in `values.yaml`. They exist so `make up` needs no setup. Replace all of them
before this is reachable by anyone but you.

## Cleanup

```
make clean
```
