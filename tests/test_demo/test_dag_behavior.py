"""Behavioural checks on the demo DAGs -- their task callables, wiring, and
retry settings. Exercises the Python inside the tasks without a scheduler or
a metadata DB. Demo-specific (task names, payload shape), so it has no
counterpart in the project1/project2 scaffolds.
"""

from __future__ import annotations

import pytest

from tests.dagtest_util import dags_in_project

from . import manifest as m

EXPECTED_ROWS = "42"


@pytest.fixture(scope="module")
def ddags(dags):
    return dags_in_project(dags, m.PROJECT)


@pytest.mark.parametrize("dag_id", sorted(m.TEAM_DAG_ROLE))
def test_team_pipeline_is_extract_then_report(dag_id, ddags):
    dag = ddags[dag_id]
    assert set(dag.task_ids) == {"extract", "report"}
    assert dag.get_task("report").upstream_task_ids == {"extract"}


@pytest.mark.parametrize("dag_id", sorted(m.TEAM_DAG_ROLE))
def test_team_pipeline_extract_payload(dag_id, ddags):
    team = dag_id.split("_")[1]  # team_a_pipeline -> "a"
    payload = ddags[dag_id].get_task("extract").python_callable()
    assert payload == {"team": team, "rows": EXPECTED_ROWS}


def test_always_fails_task_raises(ddags):
    boom = ddags["always_fails"].get_task("boom").python_callable
    with pytest.raises(RuntimeError, match="designed to fail"):
        boom()


def test_always_fails_does_not_retry(ddags):
    # default_args={"retries": 0} -- the DAG is meant to land in `failed` fast.
    assert ddags["always_fails"].get_task("boom").retries == 0
