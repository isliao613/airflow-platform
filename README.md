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

This creates the `airflow` kind cluster, builds the CVE-hardened Airflow image
from the `Dockerfile`, loads it into the cluster with `kind load` (no registry
push needed), installs the `apache-airflow/airflow` Helm chart (pinned to
`1.22.0`) from a Docker Hub OCI mirror
(`oci://registry-1.docker.io/isliao613/airflow`), and waits for everything to
come up.

The image build is the slowest step and the one most likely to fail first: it
pulls the `apache/airflow:3.3.0` base image, applies OS updates, and installs a
patched `litellm`. What gets deployed is that locally built
`isliao613/airflow:3.3.0-hardened.1`, **not** upstream `apache/airflow:3.3.0`
directly -- see `Dockerfile` for what is patched and why.

UI: http://localhost:8080 (login `admin` / `admin`, from the chart's default
`createUserJob`)

## Files

| File               | Purpose                                                              |
|--------------------|-----------------------------------------------------------------------|
| `kind-config.yaml` | Single-node kind cluster; maps NodePort `30080` -> host port `8080`  |
| `Dockerfile`       | CVE-hardened image built on `apache/airflow:3.3.0`                   |
| `values.yaml`      | Exposes `apiServer` as NodePort `30080`; chart overrides             |
| `Makefile`         | Deployment targets; source of truth for the image and version pins   |

## Targets

| Target        | Description                                        |
|---------------|-----------------------------------------------------|
| `make up`     | Create the cluster and deploy Airflow (default)     |
| `make cluster`| Create the kind cluster only                        |
| `make build`  | Build the CVE-hardened Airflow image                 |
| `make load`   | Build the image and load it into the kind cluster    |
| `make deploy` | Build, load, and install/upgrade Airflow via Helm    |
| `make status` | Show pod status                                      |
| `make logs`   | Tail scheduler logs                                  |
| `make ui`     | Print the UI URL                                     |
| `make clean`  | Uninstall Airflow and delete the kind cluster        |
| `make down`   | Alias for `make clean`                               |
| `make cluster-down` | Delete the kind cluster only                   |
| `make push`   | Push the hardened image to the registry (manual, not part of `up`) |
| `make chart-pull` | Pull the upstream chart package (for mirroring)  |
| `make chart-push` | Mirror the chart to Docker Hub as an OCI artifact (manual, not part of `up`) |

Airflow runs `CeleryExecutor` with the chart's bundled Postgres and Redis
subcharts (both enabled by default) — no external dependencies required.

## Updating the image

`IMAGE_REPO` / `IMAGE_TAG` in the Makefile are the single source of truth: the
`docker build` tag, the `kind load` tag, and the `defaultAirflowRepository` /
`defaultAirflowTag` that Helm renders into the pod spec all derive from them.
So picking up a new CVE fix is a one-line change:

1. Edit the `Dockerfile`.
2. Bump the revision suffix in `IMAGE_TAG` (`3.3.0-hardened.1` -> `.2`).
3. `make up`

Don't set the image in `values.yaml` -- `make deploy` overrides it with `--set`,
so a value there would be silently ignored while looking authoritative.

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
