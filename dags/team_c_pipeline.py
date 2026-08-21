"""Demo DAG owned by team C.

Visibility is enforced by the `access_control` mapping below: it grants the
FAB role `team_c` (mapped from the Keycloak group `airflow-team-c`) read and
edit permission on this DAG and nothing else. No team role holds the global
`DAGs` permission, so a user only ever sees the DAGs explicitly granted here.

The mapping is applied by `airflow sync-perm --include-dags`, which the
Makefile runs after the dag processor has serialized these files.
"""

from __future__ import annotations

import pendulum

from airflow.sdk import DAG, task

with DAG(
    dag_id="team_c_pipeline",
    description="Sample pipeline visible only to team C",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["team-c"],
    access_control={"team_c": {"can_read", "can_edit"}},
):

    @task
    def extract() -> dict[str, str]:
        return {"team": "c", "rows": "42"}

    @task
    def report(payload: dict[str, str]) -> str:
        message = f"team {payload['team']} processed {payload['rows']} rows"
        print(message)
        return message

    report(extract())
