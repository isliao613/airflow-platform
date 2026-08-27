"""A DAG whose task raises on every run -- always ends in `failed`.

For exercising failure paths: alerting/callbacks, retry behaviour, and
remote-log capture of tracebacks (the traceback lands in MinIO like any
other task log). No `access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

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
        raise RuntimeError("always_fails: this task is designed to fail")

    boom()
