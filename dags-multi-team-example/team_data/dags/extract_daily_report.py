from __future__ import annotations

import pendulum

from airflow.sdk import dag, task


@dag(
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["team-data"],
)
def extract_daily_report():
    @task
    def extract() -> dict:
        return {"rows": 128}

    @task
    def load(payload: dict) -> None:
        print(f"loaded {payload['rows']} rows")

    load(extract())


extract_daily_report()
