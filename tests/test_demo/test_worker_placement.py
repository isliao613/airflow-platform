"""Worker-class routing for the demo project (README: "Worker classes and
per-DAG Kubernetes pods").

Guards the queue / executor each hello_* DAG pins itself to, and keeps that
in step with chart/values.yaml -- a DAG routed to a queue with no matching
worker set would just sit queued forever. Demo-specific (task name "hello",
the KubernetesExecutor case), so no counterpart in the scaffolds.
"""

from __future__ import annotations

import pytest

from tests.dagtest_util import CHART_VALUES, dags_in_project

from . import manifest as m

yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def ddags(dags):
    return dags_in_project(dags, m.PROJECT)


def _values() -> dict:
    return yaml.safe_load(CHART_VALUES.read_text())


def _celery_queues() -> set[str]:
    return {s["queue"] for s in _values()["airflow"]["workers"]["celery"]["sets"]}


@pytest.mark.parametrize("dag_id,queue", sorted(m.QUEUE_DAG_CLASS.items()))
def test_hello_dag_pins_expected_queue(dag_id, queue, ddags):
    assert ddags[dag_id].get_task("hello").queue == queue


@pytest.mark.parametrize("dag_id,queue", sorted(m.QUEUE_DAG_CLASS.items()))
def test_queue_has_a_matching_worker_set(dag_id, queue):
    assert queue in _celery_queues(), (
        f"{dag_id} routes to queue {queue!r} with no matching set in "
        "airflow.workers.celery.sets"
    )


def test_small_is_the_default_queue(ddags):
    # README: a task with no queue at all also lands on `small`.
    assert _values()["airflow"]["config"]["operators"]["default_queue"] == "small"
    assert ddags["hello_small"].get_task("hello").queue == "small"


def test_hello_kubernetes_runs_as_its_own_pod(ddags):
    task = ddags["hello_kubernetes"].get_task("hello")
    assert task.executor == "KubernetesExecutor"
    cfg = task.executor_config or {}
    assert cfg.get("pod_override") is not None, (
        "hello_kubernetes must size itself via executor_config['pod_override']"
    )


def test_hello_kubernetes_pod_override_sets_resources(ddags):
    pytest.importorskip("kubernetes")
    pod = ddags["hello_kubernetes"].get_task("hello").executor_config["pod_override"]
    container = pod.spec.containers[0]
    assert container.resources.requests.get("cpu")
    assert container.resources.requests.get("memory")
