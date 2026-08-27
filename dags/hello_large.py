"""Hello world pinned to the `large` Celery worker class.

`queue="large"` routes this to the airflow-worker-large StatefulSet. No
`access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import socket

import pendulum
from airflow.sdk import DAG, task

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
        msg = f"hello from class=large on host={socket.gethostname()}"
        print(msg)
        return msg

    hello()
