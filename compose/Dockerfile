# CVE-hardened Airflow image for the docker-compose stack.
#
# Same base and same hardening approach as the repo-root Dockerfile, with two
# deliberate differences:
#
#   * no `COPY dags/` -- compose bind-mounts ../dags into every container
#     instead (see docker-compose.yaml), so a DAG edit is picked up by the dag
#     processor without a rebuild;
#   * no socat -- that existed only for the Keycloak sidecar in the kind
#     stack, and this stack has no SSO.
#
# `apt-get upgrade` makes the build non-reproducible on purpose: the same tag
# rebuilt later can contain different package versions. Bump IMAGE_TAG in .env
# whenever you want a rebuild to be distinguishable.
#
# No Python-package stage: Airflow 3.3.1 already ships litellm 1.85.7, past
# the three critical CVEs the kind image used to patch around. See the
# repo-root Dockerfile for that history -- if a future scan flags a bundled
# package, add a stage here and keep a `&& pip check` guard on it.
ARG AIRFLOW_VERSION=3.3.1
FROM apache/airflow:${AIRFLOW_VERSION}

USER root
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow
