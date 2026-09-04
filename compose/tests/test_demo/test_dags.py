"""Generic DAG contract for this project -- integrity and per-team
isolation, asserted against the parsed DAG objects only (no Helm chart is
read). Driven by ``manifest.py`` in this folder; byte-identical in every
tests/test_<project>/ (copy it when adding a project).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import dag_source_files, dags_in_project, flatten_access_control

from . import manifest as m

_TEAM_PERMS = {"can_read", "can_edit"}


def _pdags(dags):
    return dags_in_project(dags, m.PROJECT)


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_expected_dag_ids(dags):
    got = set(_pdags(dags))
    assert got == m.EXPECTED_DAG_IDS, f"{m.PROJECT}: {got} != {m.EXPECTED_DAG_IDS}"


def test_one_dag_per_source_file(dags):
    # every dags/<project>/*.py is named after the dag_id it defines -- this
    # also proves the project's common/ package yields no DAG of its own.
    assert {Path(d.fileloc).stem for d in _pdags(dags).values()} == m.EXPECTED_DAG_IDS
    assert {p.stem for p in dag_source_files(m.PROJECT)} == m.EXPECTED_DAG_IDS


@pytest.mark.parametrize("dag_id", sorted(m.EXPECTED_DAG_IDS))
def test_dag_hygiene(dag_id, dags):
    dag = _pdags(dags)[dag_id]
    assert dag.catchup is False, "catchup must be off (start_date is in the past)"
    assert dag.description, "every DAG sets a description"
    assert set(dag.tags), "every DAG sets at least one tag"


@pytest.mark.parametrize("dag_id,role", sorted(m.TEAM_DAG_ROLE.items()))
def test_team_dag_grants_only_its_role(dag_id, role, dags):
    acl = flatten_access_control(_pdags(dags)[dag_id])
    assert set(acl) == {role}, f"{dag_id} should grant exactly {role!r}, got {set(acl)}"
    assert acl[role] == _TEAM_PERMS


@pytest.mark.parametrize("dag_id", sorted(m.NO_ACL_DAG_IDS))
def test_non_team_dag_has_no_access_control(dag_id, dags):
    assert not flatten_access_control(_pdags(dags)[dag_id]), (
        f"{dag_id} carries access_control -- it is meant to be Admin-only (no grant)"
    )
