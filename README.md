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
```

This creates the `airflow` kind cluster, installs the `apache-airflow/airflow`
Helm chart (pinned to `1.22.0`, image pinned to `3.3.0`) from a Docker Hub OCI
mirror (`oci://registry-1.docker.io/isliao613/airflow`), and waits for
everything to come up.

UI: http://localhost:8080 (login `admin` / `admin`, from the chart's default
`createUserJob`)

## Files

| File               | Purpose                                                              |
|--------------------|-----------------------------------------------------------------------|
| `kind-config.yaml` | Single-node kind cluster; maps NodePort `30080` -> host port `8080`  |
| `values.yaml`      | Pins Airflow to `3.3.0`, exposes `apiServer` as NodePort `30080`     |
| `Makefile`         | Deployment targets                                                    |

## Targets

| Target        | Description                                        |
|---------------|-----------------------------------------------------|
| `make up`     | Create the cluster and deploy Airflow (default)     |
| `make cluster`| Create the kind cluster only                        |
| `make deploy` | Install/upgrade Airflow via Helm                     |
| `make status` | Show pod status                                      |
| `make logs`   | Tail scheduler logs                                  |
| `make ui`     | Print the UI URL                                     |
| `make clean`  | Uninstall Airflow and delete the kind cluster        |
| `make chart-pull` | Pull the upstream chart package (for mirroring)  |
| `make chart-push` | Mirror the chart to Docker Hub as an OCI artifact (manual, not part of `up`) |

Airflow runs `CeleryExecutor` with the chart's bundled Postgres and Redis
subcharts (both enabled by default) — no external dependencies required.

## Updating the chart mirror

`make deploy` installs from the Docker Hub OCI mirror, not the upstream chart
repo, so it doesn't depend on `https://airflow.apache.org` being reachable.
To pick up a new chart version:

1. Bump `CHART_VERSION` in the Makefile.
2. `helm registry login registry-1.docker.io -u isliao613`
3. `make chart-push`

## Cleanup

```
make clean
```
