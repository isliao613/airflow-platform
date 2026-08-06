# airflow-platform

One-click local deployment of Apache Airflow 3.3.0 (Helm chart 1.22.0) on a `kind` cluster.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [kind](https://kind.sigs.k8s.io/)
- [helm](https://helm.sh/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

## Quickstart

```
make up
make teams   # first deploy only -- see dags-multi-team-example/README.md
make login   # prints current UI passwords
```

`make up` builds the CVE-hardened image (see `Dockerfile`), loads it into a
fresh `airflow` kind cluster, and installs the `apache-airflow/airflow` Helm
chart (pinned to `1.22.0`). DAGs are baked into the image (`dags/`,
`dags-multi-team-example/`) so every component sees them without a PVC or
git-sync.

UI: http://localhost:8080. Login is username/password from `make login`
(`admin`, `data_user`, or `ml_user`) -- this deployment runs
`SimpleAuthManager` with multi-team enabled, a dev-only auth mode whose
passwords regenerate on every api-server restart. See
`dags-multi-team-example/README.md` for why, and for the two chart 1.22.0
limitations that shaped this setup.

## Files

| File                          | Purpose                                                              |
|-------------------------------|-----------------------------------------------------------------------|
| `kind-config.yaml`            | Single-node kind cluster; maps NodePort `30080` -> host port `8080`  |
| `values.yaml`                 | Airflow version, image, multi-team/auth config, DAG bundles          |
| `Dockerfile`                  | CVE-hardened image, DAGs baked in                                    |
| `Makefile`                    | Deployment targets                                                    |
| `dags/`                       | Global (non-team) DAGs, e.g. `hello_world.py`                        |
| `dags-multi-team-example/`    | Two example teams (`team_data`, `team_ml`), one DAG each              |

## Targets

| Target        | Description                                                    |
|---------------|-------------------------------------------------------------------|
| `make up`     | Create the cluster and deploy Airflow (default)                |
| `make cluster`| Create the kind cluster only                                    |
| `make build`  | Build the hardened image                                        |
| `make load`   | Build + load the image into kind                                |
| `make push`   | Push the image to the registry (manual, not part of `up`)       |
| `make deploy` | Build, load, and install/upgrade Airflow via Helm                |
| `make teams`  | Create the `team_data`/`team_ml` DB rows (first deploy only)     |
| `make login`  | Print current SimpleAuthManager passwords                       |
| `make status` | Show pod status                                                  |
| `make logs`   | Tail scheduler logs                                              |
| `make ui`     | Print the UI URL                                                 |
| `make clean`  | Uninstall Airflow and delete the kind cluster                    |

Airflow runs `CeleryExecutor` with the chart's bundled Postgres and Redis
subcharts (both enabled by default) — no external dependencies required.

## Cleanup

```
make clean
```
