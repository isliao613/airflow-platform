"""Behavioural checks on the demo DAGs -- their task callables, wiring, and
retry settings. Exercises the Python inside the tasks without a scheduler or
a metadata DB.
"""

from __future__ import annotations

import pytest

from dagtest_util import TEAM_DAG_ROLE

EXPECTED_ROWS = "42"


@pytest.mark.parametrize("dag_id", sorted(TEAM_DAG_ROLE))
def test_team_pipeline_is_extract_then_report(dag_id, dags):
    dag = dags[dag_id]
    assert set(dag.task_ids) == {"extract", "report"}
    assert dag.get_task("report").upstream_task_ids == {"extract"}


@pytest.mark.parametrize("dag_id", sorted(TEAM_DAG_ROLE))
def test_team_pipeline_extract_payload(dag_id, dags):
    team = dag_id.split("_")[1]  # team_a_pipeline -> "a"
    payload = dags[dag_id].get_task("extract").python_callable()
    assert payload == {"team": team, "rows": EXPECTED_ROWS}


def test_always_fails_task_raises(dags):
    boom = dags["always_fails"].get_task("boom").python_callable
    with pytest.raises(RuntimeError, match="designed to fail"):
        boom()


def test_always_fails_does_not_retry(dags):
    # default_args={"retries": 0} -- the DAG is meant to land in `failed` fast.
    assert dags["always_fails"].get_task("boom").retries == 0
