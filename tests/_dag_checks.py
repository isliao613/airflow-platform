"""Generic per-project DAG contract, driven by a project's ``manifest.py``.

These are plain assertion helpers, not ``test_`` functions. Each
``tests/test_<project>/test_dags.py`` is a thin wrapper that feeds its own
manifest in, so pytest still reports pass/fail per project while the logic
lives in one place. A manifest module must expose:

    PROJECT          str            -- folder name under dags/ and tests/test_
    EXPECTED_DAG_IDS  set[str]      -- every dag_id the project ships
    TEAM_DAG_ROLE     {dag_id: role}-- DAGs whose access_control grants one role
    QUEUE_DAG_CLASS   {dag_id: queue}
    NO_ACL_DAG_IDS    set[str]      -- DAGs that deliberately carry no grant
"""

from __future__ import annotations

from pathlib import Path

from tests.dagtest_util import (
    dag_source_files,
    dags_in_project,
    flatten_access_control,
    role_names_in_role_file,
)

EXPECTED_TEAM_PERMS = {"can_read", "can_edit"}


def _pdags(all_dags, m):
    return dags_in_project(all_dags, m.PROJECT)


def check_expected_dag_ids(all_dags, m):
    got = set(_pdags(all_dags, m))
    assert got == m.EXPECTED_DAG_IDS, (
        f"{m.PROJECT}: parsed {got} != manifest EXPECTED_DAG_IDS {m.EXPECTED_DAG_IDS}"
    )


def check_one_dag_per_source_file(all_dags, m):
    # every dags/<project>/*.py is named after the dag_id it defines -- this
    # also proves the project's common/ package yields no DAG of its own.
    from_bag = {Path(d.fileloc).stem for d in _pdags(all_dags, m).values()}
    from_disk = {p.stem for p in dag_source_files(m.PROJECT)}
    assert from_bag == m.EXPECTED_DAG_IDS
    assert from_disk == m.EXPECTED_DAG_IDS


def check_dag_hygiene(all_dags, m, dag_id):
    dag = _pdags(all_dags, m)[dag_id]
    assert dag.catchup is False, "catchup must be off (start_date is in the past)"
    assert dag.description, "every DAG sets a description"
    assert set(dag.tags), "every DAG sets at least one tag"


def check_team_dag_grants_only_its_role(all_dags, m, dag_id, role):
    acl = flatten_access_control(_pdags(all_dags, m)[dag_id])
    assert set(acl) == {role}, f"{dag_id} should grant exactly {role!r}, got {set(acl)}"
    assert acl[role] == EXPECTED_TEAM_PERMS


def check_role_defined_in_role_file(m, role):
    assert role in role_names_in_role_file(m.PROJECT), (
        f"{m.PROJECT}: a DAG grants {role!r}, but "
        f"chart/files/roles/{m.PROJECT}.json never defines that role"
    )


def check_non_team_dag_has_no_access_control(all_dags, m, dag_id):
    assert not flatten_access_control(_pdags(all_dags, m)[dag_id]), (
        f"{dag_id} carries access_control -- it is meant to be Admin-only (no grant)"
    )


def check_role_file_defines_exactly_the_team_roles(m):
    assert role_names_in_role_file(m.PROJECT) == set(m.TEAM_DAG_ROLE.values()), (
        f"chart/files/roles/{m.PROJECT}.json must define exactly the roles its "
        f"DAGs grant ({sorted(set(m.TEAM_DAG_ROLE.values()))})"
    )
