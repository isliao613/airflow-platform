"""Shared constants and helpers for the dags/ test-suite.

Pure Python -- no Airflow import -- so the checks that only exercise
dags/common/ (test_greetings.py) and the cross-file consistency checks
(roles.json / values.yaml) work even without Airflow installed.
"""

from __future__ import annotations

import json
from pathlib import Path

# tests/ sits at the repo root, next to dags/. In the `make test` container it
# is mounted at /opt/airflow/tests, so REPO_ROOT resolves to /opt/airflow --
# which is where the DAGs (baked in) and the mounted chart/ live too.
TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
DAGS_DIR = REPO_ROOT / "dags"
ROLES_JSON = REPO_ROOT / "chart" / "files" / "roles.json"
CHART_VALUES = REPO_ROOT / "chart" / "values.yaml"

# The DAGs baked into the image (Dockerfile: `COPY dags/`). Kept explicit so a
# file that silently stops defining a DAG -- or an unexpected new one -- fails
# the suite instead of slipping through.
EXPECTED_DAG_IDS = {
    "team_a_pipeline",
    "team_b_pipeline",
    "team_c_pipeline",
    "hello_small",
    "hello_medium",
    "hello_large",
    "hello_kubernetes",
    "always_fails",
}

# dag_id -> the single FAB role its access_control grants. Each role name must
# also be defined in chart/files/roles.json (test_access_control checks that).
TEAM_DAG_ROLE = {
    "team_a_pipeline": "team_a",
    "team_b_pipeline": "team_b",
    "team_c_pipeline": "team_c",
}

# dag_id -> the Celery queue / worker class the DAG's task pins itself to. The
# queue names must match a set in airflow.workers.celery.sets
# (chart/values.yaml).
QUEUE_DAG_CLASS = {
    "hello_small": "small",
    "hello_medium": "medium",
    "hello_large": "large",
}

# DAGs that deliberately carry NO access_control -- README: "only the Airflow
# Admin role sees it", because no team role holds the global DAGs permission.
NO_ACL_DAG_IDS = {
    "hello_small",
    "hello_medium",
    "hello_large",
    "hello_kubernetes",
    "always_fails",
}


def dag_source_files() -> list[Path]:
    """Every top-level DAG module in dags/ (excludes the common/ package)."""
    return sorted(p for p in DAGS_DIR.glob("*.py") if p.name != "__init__.py")


def role_names_in_roles_json() -> set[str]:
    data = json.loads(ROLES_JSON.read_text())
    return {entry["name"] for entry in data}


def flatten_access_control(dag) -> dict[str, set[str]]:
    """Normalise DAG.access_control to {role: {permission, ...}}.

    Airflow accepts (and, depending on the version, stores) either
    ``{role: {perms}}`` or the expanded ``{role: {resource: {perms}}}`` form.
    Collapse both to a flat permission set so assertions don't depend on which
    one this Airflow keeps.
    """
    out: dict[str, set[str]] = {}
    for role, entry in (getattr(dag, "access_control", None) or {}).items():
        if isinstance(entry, dict):
            perms: set[str] = set()
            for value in entry.values():
                perms |= set(value)
            out[role] = perms
        else:
            out[role] = set(entry)
    return out
