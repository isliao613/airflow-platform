"""Behavioural checks on the demo DAGs -- their task callables and wiring.

Exercises the Python inside the tasks without a scheduler or a metadata DB.
Demo-specific (task names, payload shape), so a new project would not copy it.
"""

from __future__ import annotations

import pytest

from tests.conftest import dags_in_project

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


@pytest.mark.parametrize("dag_id", sorted(m.NO_ACL_DAG_IDS))
def test_hello_dag_has_a_single_hello_task(dag_id, ddags):
    assert set(ddags[dag_id].task_ids) == {"hello"}
