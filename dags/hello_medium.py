"""Hello world pinned to the `medium` Celery worker class.

`queue="medium"` routes this to the airflow-worker-medium StatefulSet. No
`access_control` -> only the Airflow Admin role sees it.
"""

from __future__ import annotations

import socket

import pendulum
from airflow.sdk import DAG, task

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
        msg = f"hello from class=medium on host={socket.gethostname()}"
        print(msg)
        return msg

    hello()
