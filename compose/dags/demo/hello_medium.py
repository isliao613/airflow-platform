"""Hello world pinned to the `medium` Celery worker class.

`queue="medium"` routes this to the airflow-worker-medium service. Uses
the shared helper `demo.common.greetings.where` (see `dags/demo/common/`). No
`access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from demo.common.greetings import where

with DAG(
    dag_id="hello_medium",
    description="Hello world on the medium worker class",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "worker-class"],
):

    @task(queue="medium")
    def hello() -> str:
        return where("hello from class=medium")

    hello()
