"""Hello world pinned to the `small` Celery worker class.

`queue="small"` is also `operators.default_queue`, so a task with no queue
at all lands here too. No `access_control` -> only the Airflow Admin role
sees it.
"""

from __future__ import annotations

import socket

import pendulum
from airflow.sdk import DAG, task

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
        msg = f"hello from class=small on host={socket.gethostname()}"
        print(msg)
        return msg

    hello()
