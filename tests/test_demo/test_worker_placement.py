"""Worker-class routing for the demo project (README: "Worker classes and
per-DAG Kubernetes pods").

Asserts only what the DAG files themselves declare: the Celery queue each
``hello_*`` task pins itself to, that ``hello_world`` pins none so it falls
through to ``operators.default_queue``, and that ``hello_kubernetes`` runs as
its own pod. Whether a matching Celery worker set actually exists for that queue
(``airflow.workers.celery.sets`` in ``chart/values.yaml``) is a deploy-time
concern and is deliberately NOT checked here -- unit tests read only
``dags/`` and the project manifest, never the Helm chart. That
queue<->worker-set consistency is covered by the `make up` smoke check
instead.

Demo-specific (task name "hello", the KubernetesExecutor case), so no
counterpart in the project1/project2 scaffolds.
"""

from __future__ import annotations

import pytest

from tests.conftest import dags_in_project

from . import manifest as m


@pytest.fixture(scope="module")
def ddags(dags):
    return dags_in_project(dags, m.PROJECT)


@pytest.mark.parametrize("dag_id,queue", sorted(m.QUEUE_DAG_CLASS.items()))
def test_hello_dag_pins_expected_queue(dag_id, queue, ddags):
    assert ddags[dag_id].get_task("hello").queue == queue


def test_hello_world_takes_the_default_queue(ddags):
    # hello_world deliberately names no queue. Compare against the configured
    # default rather than a literal, so this asserts "it did not pin one"
    # instead of hard-coding whatever `operators.default_queue` happens to be.
    from airflow.configuration import conf

    assert ddags["hello_world"].get_task("hello").queue == conf.get(
        "operators", "default_queue"
    )


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
