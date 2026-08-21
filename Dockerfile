FROM apache/airflow:3.3.0

# --- OS package CVEs --------------------------------------------------------
# Critical CVEs currently flagged by Trivy against this image's Debian 12
# packages (libperl5.36/perl/perl-base/perl-modules-5.36: CVE-2026-13221,
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
# socat backs the api-server sidecar that publishes Keycloak on 127.0.0.1:8081
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
# litellm 1.82.6, bundled by the base image, carries 3 critical CVEs that DO
# have upstream fixes: CVE-2026-35030 (fixed 1.83.0), CVE-2026-42208 (fixed
# 1.83.7), CVE-2026-49468 (fixed 1.84.0). Pin to a tested patched release.
#
# This deliberately departs from Airflow 3.3.0's own constraints file, which
# pins litellm==1.82.6. 1.95.0's requirement ranges (httpx>=0.28, openai>=2.20,
# pydantic>=2.10, tokenizers>=0.21) are all satisfied by what Airflow already
# pins, so nothing shared should move -- `pip check` fails the build if that
# stops being true instead of letting a broken image reach the cluster.
USER airflow
RUN pip install --no-cache-dir "litellm==1.95.0" \
    && pip check

# --- Platform content -------------------------------------------------------
# DAGs and the SSO config ship in the image, so the cluster needs no DAG volume,
# no gitSync, and no registry: `make load` side-loads the lot into kind.
COPY --chown=airflow:root dags/ /opt/airflow/dags/
COPY --chown=airflow:root airflow/webserver_config.py /opt/airflow/webserver_config.py
