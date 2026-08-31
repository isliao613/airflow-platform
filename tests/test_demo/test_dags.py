"""Generic DAG contract for this project -- integrity and per-team
isolation, asserted against the parsed DAG objects only (no Helm chart is
read). All cases are driven by ``manifest.py`` in this folder; the logic
lives in ``tests/_dag_checks.py`` and is identical for every project, so
this file is the same in each tests/test_<project>/.
"""

from __future__ import annotations

import pytest

from tests import _dag_checks as c

from . import manifest as m


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_expected_dag_ids(dags):
    c.check_expected_dag_ids(dags, m)


def test_one_dag_per_source_file(dags):
    c.check_one_dag_per_source_file(dags, m)


@pytest.mark.parametrize("dag_id", sorted(m.EXPECTED_DAG_IDS))
def test_dag_hygiene(dag_id, dags):
    c.check_dag_hygiene(dags, m, dag_id)


@pytest.mark.parametrize("dag_id,role", sorted(m.TEAM_DAG_ROLE.items()))
def test_team_dag_grants_only_its_role(dag_id, role, dags):
    c.check_team_dag_grants_only_its_role(dags, m, dag_id, role)


@pytest.mark.parametrize("dag_id", sorted(m.NO_ACL_DAG_IDS))
def test_non_team_dag_has_no_access_control(dag_id, dags):
    c.check_non_team_dag_has_no_access_control(dags, m, dag_id)
