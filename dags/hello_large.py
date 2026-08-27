"""Hello world pinned to the `large` Celery worker class.

`queue="large"` routes this to the airflow-worker-large Deployment. Uses
the shared helper `common.greetings.where` (see `dags/common/`). No
`access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from common.greetings import where

with DAG(
    dag_id="hello_large",
    description="Hello world on the large worker class",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "worker-class"],
):

    @task(queue="large")
    def hello() -> str:
        return where("hello from class=large")

    hello()
