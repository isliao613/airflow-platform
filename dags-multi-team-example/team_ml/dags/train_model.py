from __future__ import annotations

import pendulum

from airflow.sdk import dag, task


@dag(
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["team-ml"],
)
def train_model():
    @task
    def fetch_features() -> int:
        return 4096

    @task
    def train(num_features: int) -> None:
        print(f"training on {num_features} features")

    train(fetch_features())


train_model()
