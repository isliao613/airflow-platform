"""The simplest DAG this platform ships -- one task, no routing, no grants.

Pins no `queue`, so the task lands on whatever `operators.default_queue` names
(`small` here, set in docker-compose.yaml). That is the point of having it
alongside
`hello_small.py`: that file proves an EXPLICIT queue reaches the class it names,
this one proves the DEFAULT path works without a DAG author choosing anything.

Uses the shared helper `demo.common.greetings.where` (see `dags/demo/common/`),
so it also verifies the common-folder import resolves. No `access_control` ->
only the Airflow Admin role sees it.

This is the DAG to trigger first when checking that a fresh stack works: it
exercises the scheduler, the broker, a Celery worker and the shared log volume,
and needs nothing configured beyond the defaults.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from demo.common.greetings import where

with DAG(
    dag_id="hello_world",
    description="Hello world on the default worker class",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "smoke"],
):

    @task
    def hello() -> str:
        return where("hello from the default class")

    hello()
