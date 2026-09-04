"""What the ``demo`` project ships -- the single source of truth its tests
assert against. Mirrors ``compose/dags/demo/`` and ``compose/roles/demo.json``.

A file that silently stops defining a DAG -- or an unexpected new one --
fails ``test_dags.py`` instead of slipping through.
"""

from __future__ import annotations

PROJECT = "demo"

EXPECTED_DAG_IDS = {
    "team_a_pipeline",
    "team_b_pipeline",
    "team_c_pipeline",
    "hello_world",
    "hello_small",
    "hello_medium",
    "hello_large",
}

# dag_id -> the single FAB role its access_control grants. test_dags asserts
# the DAG grants exactly this role {can_read, can_edit}. That a matching role
# exists in roles/demo.json, and that a user holds it, are deploy concerns
# (bootstrap/init.sh), not checked here.
TEAM_DAG_ROLE = {
    "team_a_pipeline": "team_a",
    "team_b_pipeline": "team_b",
    "team_c_pipeline": "team_c",
}

# dag_id -> the Celery queue / worker class the DAG's task pins itself to.
# test_worker_placement.py asserts the DAG declares exactly this queue; that a
# matching airflow-worker-<class> service exists in docker-compose.yaml is a
# deploy concern, checked by the `make up` smoke run.
QUEUE_DAG_CLASS = {
    "hello_small": "small",
    "hello_medium": "medium",
    "hello_large": "large",
}

# DAGs that deliberately carry NO access_control -- "only the Airflow Admin
# role sees it", because no team role holds the global DAGs permission.
NO_ACL_DAG_IDS = {
    "hello_world",
    "hello_small",
    "hello_medium",
    "hello_large",
}
