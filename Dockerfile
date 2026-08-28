FROM apache/airflow:3.3.1

# --- OS package CVEs --------------------------------------------------------
# Critical CVEs flagged by Trivy against the Debian 12 packages in the base
# image -- last scanned against apache/airflow:3.3.0, NOT re-scanned for
# 3.3.1; re-run Trivy to refresh this list. At that scan:
# (libperl5.36/perl/perl-base/perl-modules-5.36: CVE-2026-13221,
# CVE-2026-42496, CVE-2026-57433, CVE-2026-8376; libsqlite3-0/sqlite3:
# CVE-2025-7458; libxml2: CVE-2026-6653; openssh-client: CVE-2026-60002;
# zlib1g: CVE-2023-45853) have no fix published by Debian yet (status:
# affected / fix_deferred / will_not_fix upstream). `apt-get upgrade` still
# runs so any patch Debian ships lands automatically on the next rebuild.
#
# Note that this makes the build non-reproducible on purpose: the same image
# tag rebuilt later can contain different package versions. Bump IMAGE_TAG in
# the Makefile whenever you want a rebuild to be distinguishable.
#
# socat backs the api-server sidecar that publishes Keycloak on 127.0.0.1:8181
# inside the pod (see apiServer.extraContainers in values.yaml). Installing it
# here avoids pulling a second image into the kind cluster just to proxy a port.
USER root
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends socat \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Python package CVEs ----------------------------------------------------
# No Python patch is applied any more. The 3 critical litellm CVEs this stage
# used to exist for -- CVE-2026-35030 (fixed 1.83.0), CVE-2026-42208 (fixed
# 1.83.7), CVE-2026-49468 (fixed 1.84.0) -- were a 3.3.0 problem: that
# release's constraints pinned litellm==1.82.6. Airflow 3.3.1 ships
# litellm==1.85.7 (verified with `pip show litellm` in the base image), which
# is past all three, and OSV reports no known advisory affecting 1.85.7.
#
# The old `pip install litellm==1.95.0` is also actively incompatible with
# 3.3.1: apache-airflow-providers-google 22.3.0 requires litellm<1.86.0, so
# `pip check` fails the build. Overriding it would mean shipping a broken
# provider to fix CVEs that are already fixed.
#
# If a future scan flags the bundled litellm, re-add a stage here -- and keep
# the `&& pip check` guard, which is what caught the conflict above.
USER airflow

# --- Platform content -------------------------------------------------------
# DAGs ship in the image, so the cluster needs no DAG volume, no gitSync, and
# no registry: `make load` side-loads them into kind. The SSO config
# (webserver_config.py) is NOT baked in here -- it's set via
# apiServer.apiServerConfig / webserver.webserverConfig in values.yaml
# instead, so editing it only needs `make deploy`, not a full image rebuild.
COPY --chown=airflow:root dags/ /opt/airflow/dags/
