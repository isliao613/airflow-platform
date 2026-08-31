"""Cross-project invariants over dags/ and tests/ that no single
tests/test_<project>/ can see (still no Helm chart is read):

  * every dags/<project>/ has a matching tests/test_<project>/manifest.py
    (and vice versa) -- add a project and forget its tests, this fails;
  * the manifests collectively account for every parsed DAG, with no dag_id
    claimed by two projects.
"""

from __future__ import annotations

import importlib

from tests.dagtest_util import (
    discover_dag_projects,
    discover_test_projects,
    project_of,
)


def _manifest(project: str):
    return importlib.import_module(f"tests.test_{project}.manifest")


def test_dag_projects_and_test_projects_match_one_to_one():
    assert discover_dag_projects() == discover_test_projects(), (
        "each dags/<project>/ needs a tests/test_<project>/manifest.py and "
        "vice versa"
    )


def test_manifests_account_for_every_parsed_dag(dags):
    parsed: dict[str, set[str]] = {}
    for dag_id, dag in dags.items():
        parsed.setdefault(project_of(dag.fileloc), set()).add(dag_id)

    for project in discover_dag_projects():
        expected = _manifest(project).EXPECTED_DAG_IDS
        assert parsed.get(project, set()) == expected, (
            f"{project}: parsed {parsed.get(project, set())} != manifest {expected}"
        )


def test_dag_ids_are_unique_across_projects(dags):
    union: set[str] = set()
    overlap: set[str] = set()
    for project in discover_test_projects():
        ids = _manifest(project).EXPECTED_DAG_IDS
        overlap |= union & ids
        union |= ids
    assert not overlap, f"dag_id(s) claimed by more than one project: {sorted(overlap)}"
    assert set(dags) == union
