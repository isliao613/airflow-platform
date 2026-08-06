FROM apache/airflow:3.3.0

# --- OS package CVEs --------------------------------------------------------
# Critical CVEs currently flagged by Trivy against this image's Debian 12
# packages (libperl5.36/perl/perl-base/perl-modules-5.36: CVE-2026-13221,
# CVE-2026-42496, CVE-2026-57433, CVE-2026-8376; libsqlite3-0/sqlite3:
# CVE-2025-7458; libxml2: CVE-2026-6653; openssh-client: CVE-2026-60002;
# zlib1g: CVE-2023-45853) have no fix published by Debian yet (status:
# affected / fix_deferred / will_not_fix upstream). `apt-get upgrade` still
# runs so any patch Debian ships lands automatically on the next rebuild.
USER root
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Python package CVEs ----------------------------------------------------
# litellm 1.82.6, bundled by the base image, carries 3 critical CVEs that DO
# have upstream fixes: CVE-2026-35030 (fixed 1.83.0), CVE-2026-42208 (fixed
# 1.83.7), CVE-2026-49468 (fixed 1.84.0). Pin to a tested patched release.
USER airflow
RUN pip install --no-cache-dir "litellm==1.95.0"
