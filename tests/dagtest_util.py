"""Shared constants and pure helpers for the dags/ test-suite.

Pure Python -- no Airflow import -- so the checks that only exercise a
project's ``common/`` package (each ``tests/test_<project>/test_greetings.py``)
and the cross-file consistency checks (role files / values.yaml) work even
without Airflow installed.

Layout: every ``dags/<project>/`` is a self-contained Python package (its own
``__init__.py`` and ``common/`` subpackage -- projects are fully independent
and never import one another). ``tests/test_<project>/`` mirrors it and
carries a ``manifest.py`` stating exactly what that project ships; the
generic contract in ``tests/_dag_checks.py`` is driven entirely by that
manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

# tests/ sits at the repo root, next to dags/. In the `make test` container it
# is mounted at /opt/airflow/tests, so REPO_ROOT resolves to /opt/airflow --
# where the DAGs (baked in) and the mounted chart/ live too.
TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
DAGS_DIR = REPO_ROOT / "dags"
ROLES_DIR = REPO_ROOT / "chart" / "files" / "roles"
CHART_VALUES = REPO_ROOT / "chart" / "values.yaml"

# FAB built-ins -- no per-project role file may (re)define them.
BUILTIN_ROLES = {"Admin", "Public", "Op", "Viewer", "User"}

_NON_PROJECT_DIRS = {"__pycache__"}


def discover_dag_projects() -> set[str]:
    """Every project package under dags/ (a directory with an __init__.py)."""
    return {
        p.name
        for p in DAGS_DIR.iterdir()
        if p.is_dir()
        and p.name not in _NON_PROJECT_DIRS
        and (p / "__init__.py").is_file()
    }


def discover_test_projects() -> set[str]:
    """Every tests/test_<project>/ package that carries a manifest.py."""
    return {
        p.name[len("test_"):]
        for p in TESTS_DIR.iterdir()
        if p.is_dir() and p.name.startswith("test_") and (p / "manifest.py").is_file()
    }


def project_of(fileloc: str) -> str:
    """The project a parsed DAG belongs to, taken from its file path."""
    return Path(fileloc).resolve().relative_to(DAGS_DIR).parts[0]


def dags_in_project(dags: dict, project: str) -> dict:
    """Subset of a DagBag's {dag_id: DAG} that lives under dags/<project>/."""
    return {d_id: d for d_id, d in dags.items() if project_of(d.fileloc) == project}


def dag_source_files(project: str) -> list[Path]:
    """Top-level DAG modules in dags/<project>/ (excludes __init__ and common/)."""
    return sorted(
        p for p in (DAGS_DIR / project).glob("*.py") if p.name != "__init__.py"
    )


def role_file(project: str) -> Path:
    return ROLES_DIR / f"{project}.json"


def role_names_in_role_file(project: str) -> set[str]:
    return {entry["name"] for entry in json.loads(role_file(project).read_text())}


def all_role_names() -> set[str]:
    names: set[str] = set()
    for f in sorted(ROLES_DIR.glob("*.json")):
        names |= {entry["name"] for entry in json.loads(f.read_text())}
    return names


def flatten_access_control(dag) -> dict[str, set[str]]:
    """Normalise DAG.access_control to {role: {permission, ...}}.

    Airflow accepts (and, depending on the version, stores) either
    ``{role: {perms}}`` or the expanded ``{role: {resource: {perms}}}`` form.
    Collapse both to a flat permission set so assertions don't depend on which
    one this Airflow keeps.
    """
    out: dict[str, set[str]] = {}
    for role, entry in (getattr(dag, "access_control", None) or {}).items():
        if isinstance(entry, dict):
            perms: set[str] = set()
            for value in entry.values():
                perms |= set(value)
            out[role] = perms
        else:
            out[role] = set(entry)
    return out
