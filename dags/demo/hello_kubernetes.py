"""Hello world that runs as its own Kubernetes pod.

`executor="KubernetesExecutor"` (Airflow 3 multi-executor) makes the task
run in a dedicated pod instead of on a Celery worker; `pod_override` sizes
it inline. Uses the shared helper `demo.common.greetings.where` (see
`dags/demo/common/`) -- which also proves the common-folder import works from a
pod built off the same image. No `access_control` -> only the Airflow Admin
role sees it.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG, task

from demo.common.greetings import where

try:
    from kubernetes.client import models as k8s

    _POD = k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    resources=k8s.V1ResourceRequirements(
                        requests={"cpu": "250m", "memory": "512Mi"},
                        limits={"cpu": "500m", "memory": "512Mi"},
                    ),
                )
            ]
        )
    )
except Exception:  # pragma: no cover - kubernetes client always present in-image
    _POD = None

with DAG(
    dag_id="hello_kubernetes",
    description="Hello world in its own Kubernetes pod",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["platform", "worker-class"],
):

    @task(executor="KubernetesExecutor", executor_config={"pod_override": _POD})
    def hello() -> str:
        return where("hello from class=kubernetes")

    hello()
