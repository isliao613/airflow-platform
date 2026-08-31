"""A DAG whose task raises on every run -- always ends in `failed`.

For exercising failure paths: alerting/callbacks, retry behaviour, and
remote-log capture of tracebacks. The raise comes from
`demo.common.greetings.fail` -- a shared module in `dags/demo/common/` -- so this DAG
also verifies the common-folder import. No `access_control` -> only the
Airflow Admin role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from demo.common.greetings import fail

with DAG(
    dag_id="always_fails",
    description="Task raises on every run -- always ends failed",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "demo", "failure"],
    default_args={"retries": 0},
):

    @task
    def boom() -> None:
        fail("always_fails: this task is designed to fail")

    boom()
