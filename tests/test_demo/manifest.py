"""What the ``demo`` project ships -- the single source of truth its tests
assert against. Mirrors ``dags/demo/`` and ``chart/files/roles/demo.json``.

A file that silently stops defining a DAG -- or an unexpected new one --
fails ``test_dags.py`` instead of slipping through.
"""

from __future__ import annotations

PROJECT = "demo"

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
# also be defined in chart/files/roles/demo.json (test_dags checks that).
TEAM_DAG_ROLE = {
    "team_a_pipeline": "team_a",
    "team_b_pipeline": "team_b",
    "team_c_pipeline": "team_c",
}

# dag_id -> the Celery queue / worker class the DAG's task pins itself to. The
# queue names must match a set in airflow.workers.celery.sets
# (chart/values.yaml); test_worker_placement.py checks that.
QUEUE_DAG_CLASS = {
    "hello_small": "small",
    "hello_medium": "medium",
    "hello_large": "large",
}

# DAGs that deliberately carry NO access_control -- "only the Airflow Admin
# role sees it", because no team role holds the global DAGs permission.
NO_ACL_DAG_IDS = {
    "hello_small",
    "hello_medium",
    "hello_large",
    "hello_kubernetes",
    "always_fails",
}
