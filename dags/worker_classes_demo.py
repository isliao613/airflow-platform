"""Demonstrates the worker-class routing wired up in chart/values.yaml.

Four tasks, four placements:

* ``on_small``   -- no ``queue`` -> the default queue ``small`` (operators.
  default_queue), so it runs on the base Celery worker ``<release>-worker``.
* ``on_medium`` / ``on_large`` -- ``queue=`` pins the task to that Celery
  worker class (``<release>-worker-medium`` / ``-large``), which has more
  CPU/memory.
* ``on_own_pod`` -- ``executor="KubernetesExecutor"`` (Airflow 3
  multi-executor) makes this one task run as its OWN pod, sized right here
  via ``executor_config={"pod_override": ...}`` -- for one-off resource
  needs that don't fit a fixed class.

No ``access_control`` -> only the Airflow ``Admin`` role sees it; it's a
platform demo, not a team pipeline.
"""

from __future__ import annotations

import socket

import pendulum
from airflow.sdk import DAG, task

try:
    from kubernetes.client import models as k8s

    _BIG_POD = k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    resources=k8s.V1ResourceRequirements(
                        requests={"cpu": "500m", "memory": "1Gi"},
                        limits={"cpu": "1", "memory": "1Gi"},
                    ),
                )
            ]
        )
    )
except Exception:  # pragma: no cover - kubernetes client always present in-image
    _BIG_POD = None


def _where(label: str) -> str:
    host = socket.gethostname()
    print(f"{label} ran on {host}")
    return host


with DAG(
    dag_id="worker_classes_demo",
    description="One task per worker class + one in its own Kubernetes pod",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "demo"],
):

    @task
    def on_small() -> str:
        return _where("small (default queue)")

    @task(queue="medium")
    def on_medium() -> str:
        return _where("medium")

    @task(queue="large")
    def on_large() -> str:
        return _where("large")

    @task(executor="KubernetesExecutor", executor_config={"pod_override": _BIG_POD})
    def on_own_pod() -> str:
        return _where("kubernetes pod")

    on_small()
    on_medium()
    on_large()
    on_own_pod()
