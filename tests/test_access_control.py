"""The per-team DAG isolation contract (README: "How the isolation works").

Each team DAG grants exactly one role ``{can_read, can_edit}`` and nothing
else; every other DAG carries no access_control at all, so only Admin -- the
one role holding the global ``DAGs`` permission -- sees it. A typo in a
DAG's ``access_control`` key, or a role that roles.json never defines, would
silently make that DAG invisible to its team; these tests turn that into a
failure.
"""

from __future__ import annotations

import pytest

from dagtest_util import (
    NO_ACL_DAG_IDS,
    TEAM_DAG_ROLE,
    flatten_access_control,
    role_names_in_roles_json,
)

EXPECTED_PERMS = {"can_read", "can_edit"}


@pytest.mark.parametrize("dag_id,role", sorted(TEAM_DAG_ROLE.items()))
def test_team_dag_grants_only_its_own_role(dag_id, role, dags):
    acl = flatten_access_control(dags[dag_id])
    assert set(acl) == {role}, f"{dag_id} should grant exactly {role!r}, got {set(acl)}"
    assert acl[role] == EXPECTED_PERMS


@pytest.mark.parametrize("dag_id,role", sorted(TEAM_DAG_ROLE.items()))
def test_team_role_is_defined_in_roles_json(dag_id, role):
    assert role in role_names_in_roles_json(), (
        f"{dag_id} grants {role!r}, but chart/files/roles.json never defines that role"
    )


@pytest.mark.parametrize("dag_id", sorted(NO_ACL_DAG_IDS))
def test_non_team_dag_has_no_access_control(dag_id, dags):
    assert not flatten_access_control(dags[dag_id]), (
        f"{dag_id} carries access_control -- it is meant to be Admin-only (no grant)"
    )


def test_roles_json_defines_the_team_roles_and_no_extras():
    assert role_names_in_roles_json() == set(TEAM_DAG_ROLE.values())
