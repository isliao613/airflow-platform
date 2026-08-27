"""Hello world pinned to the `small` Celery worker class.

`queue="small"` is also `operators.default_queue`, so a task with no queue
at all lands here too. Uses `common.greetings.where` -- a shared module in
`dags/common/` -- so this DAG also verifies that the common-folder import
resolves. No `access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from common.greetings import where

with DAG(
    dag_id="hello_small",
    description="Hello world on the small worker class",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "worker-class"],
):

    @task(queue="small")
    def hello() -> str:
        return where("hello from class=small")

    hello()
