"""Demo DAG owned by project1.

Same per-team isolation contract as the ``demo`` project's team pipelines:
the ``access_control`` mapping grants exactly one FAB role -- ``project1``,
mapped from the Keycloak group ``airflow-project1`` -- read and edit
permission on this DAG and nothing else. No project role holds the global
``DAGs`` permission, so a user only ever sees the DAGs explicitly granted
here. The role itself is defined in ``chart/files/roles/project1.json`` and
the mapping is applied by ``airflow sync-perm --include-dags`` (the
sync-roles hook Job).

Imports the project's own helper via ``from project1.common.greetings import
...`` -- proving the per-project ``common/`` package ships and resolves.
"""

from __future__ import annotations

import pendulum

from airflow.sdk import DAG, task

from project1.common.greetings import where

with DAG(
    dag_id="project1_pipeline",
    description="Sample pipeline visible only to project1",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["project1"],
    access_control={"project1": {"can_read", "can_edit"}},
):

    @task
    def extract() -> dict[str, str]:
        return {"project": "project1", "rows": "42"}

    @task
    def report(payload: dict[str, str]) -> str:
        return where(f"project1 processed {payload['rows']} rows")

    report(extract())
