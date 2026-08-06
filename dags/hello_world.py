from __future__ import annotations

import pendulum

from airflow.sdk import dag, task


@dag(
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
)
def hello_world():
    @task
    def say_hello() -> str:
        return "Hello, Airflow!"

    @task
    def log_greeting(greeting: str) -> None:
        print(greeting)

    log_greeting(say_hello())


hello_world()
