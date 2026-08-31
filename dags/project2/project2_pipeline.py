"""Demo DAG owned by project2.

Same per-team isolation contract as the ``demo`` project's team pipelines:
the ``access_control`` mapping grants exactly one FAB role -- ``project2``,
mapped from the Keycloak group ``airflow-project2`` -- read and edit
permission on this DAG and nothing else. No project role holds the global
``DAGs`` permission, so a user only ever sees the DAGs explicitly granted
here. The role itself is defined in ``chart/files/roles/project2.json`` and
the mapping is applied by ``airflow sync-perm --include-dags`` (the
sync-roles hook Job).

Imports the project's own helper via ``from project2.common.greetings import
...`` -- proving the per-project ``common/`` package ships and resolves.
"""

from __future__ import annotations

import pendulum

from airflow.sdk import DAG, task

from project2.common.greetings import where

with DAG(
    dag_id="project2_pipeline",
    description="Sample pipeline visible only to project2",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["project2"],
    access_control={"project2": {"can_read", "can_edit"}},
):

    @task
    def extract() -> dict[str, str]:
        return {"project": "project2", "rows": "42"}

    @task
    def report(payload: dict[str, str]) -> str:
        return where(f"project2 processed {payload['rows']} rows")

    report(extract())
