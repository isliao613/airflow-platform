"""Worker-class routing for the demo project (README: "Worker classes").

Asserts only what the DAG files themselves declare: the Celery queue each
``hello_*`` task pins itself to, and that ``hello_world`` pins none so it falls
through to the configured default. Whether a matching ``airflow-worker-<class>``
service actually exists for that queue is a deploy-time concern and is
deliberately NOT checked here -- unit tests read only ``dags/`` and the project
manifest, never docker-compose.yaml. That queue<->service consistency is covered
by the `make up` smoke run instead.

Demo-specific (the task is named "hello"), so a new project would not copy it.
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


def test_no_task_names_an_executor(dags):
    """This stack configures CeleryExecutor alone (docker-compose.yaml).

    An executor a task names but the deployment does not configure is a hard
    DAG *parse* error, not a run-time one (``UnknownExecutorException`` out of
    ``_validate_executor_fields``), so one such task takes the DAG out of the UI
    entirely. Route with ``queue=`` instead -- that is what the worker classes
    are for.
    """
    offenders = {
        f"{dag_id}.{task.task_id}": task.executor
        for dag_id, dag in dags.items()
        for task in dag.tasks
        if getattr(task, "executor", None) is not None
    }
    assert not offenders, (
        f"tasks naming an executor: {offenders}. This stack runs CeleryExecutor "
        "only -- route with queue= instead."
    )
