"""Demo DAG owned by team A.

Visibility is enforced by the `access_control` mapping below: it grants the
FAB role `team_a` read and edit permission on this DAG and nothing else. No
team role holds the global `DAGs` permission, so a user only ever sees the DAGs
explicitly granted here.

The role itself is defined in `roles/demo.json` and held by the local user
`alice`, created by `bootstrap/init.sh` -- there is no identity provider in this
stack. The mapping is applied by `airflow sync-perm --include-dags`, which
`bootstrap/sync-perm.sh` runs once the dag processor has serialized these files.
"""

from __future__ import annotations

import pendulum

from airflow.sdk import DAG, task

with DAG(
    dag_id="team_a_pipeline",
    description="Sample pipeline visible only to team A",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["team-a"],
    access_control={"team_a": {"can_read", "can_edit"}},
):

    @task
    def extract() -> dict[str, str]:
        return {"team": "a", "rows": "42"}

    @task
    def report(payload: dict[str, str]) -> str:
        message = f"team {payload['team']} processed {payload['rows']} rows"
        print(message)
        return message

    report(extract())
