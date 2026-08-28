"""dags/ parses cleanly and defines exactly the DAGs the platform expects.

The import-error check is the single most important guard: it exercises the
litellm / kubernetes imports and -- because every demo DAG does
``from common.greetings import ...`` -- proves dags/common/ ships and
imports (README: "the import doubles as a check that the folder ships in the
image").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dagtest_util import EXPECTED_DAG_IDS, dag_source_files


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_exactly_the_expected_dags(dags):
    assert set(dags) == EXPECTED_DAG_IDS


def test_one_dag_per_source_file(dags):
    # every dags/*.py is named after the dag_id it defines -- this also proves
    # dags/common/greetings.py yields no DAG of its own.
    assert {Path(d.fileloc).stem for d in dags.values()} == EXPECTED_DAG_IDS


def test_common_package_not_parsed_as_a_dag(dagbag):
    assert not any("common" in str(path) for path in dagbag.import_errors)


@pytest.mark.parametrize("path", dag_source_files(), ids=lambda p: p.name)
def test_source_file_defines_its_dag(path, dags):
    assert path.stem in dags, f"{path.name} defines no DAG called {path.stem!r}"


@pytest.mark.parametrize("dag_id", sorted(EXPECTED_DAG_IDS))
def test_dag_hygiene(dag_id, dags):
    dag = dags[dag_id]
    assert dag.catchup is False, "catchup must be off (start_date is in the past)"
    assert dag.description, "every DAG sets a description"
    assert set(dag.tags), "every DAG sets at least one tag"
