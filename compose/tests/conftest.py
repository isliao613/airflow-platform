"""Test bootstrap AND shared helpers for this stack's ``dags/`` unit suite.

Everything the suite needs that is not itself a test lives here: the
pre-import environment setup, the session DagBag fixtures, and the
pure-Python helpers (project discovery, DagBag slicing, access_control
flattening). Test files import the helpers with ``from tests.conftest
import ...``. The suite reads only ``compose/dags/`` and each project's
``tests/test_<project>/manifest.py`` -- never docker-compose.yaml or
``roles/``.

This is the compose stack's OWN suite, over its OWN ``dags/``. The repo root
has a separate stack with a separate tree and a separate suite; the two are
independent by design, so nothing here reaches outside ``compose/``.

Module-level code runs before any test imports Airflow, so the DagBag sees
the same environment the containers do: examples off, ``CeleryExecutor``
(matching ``AIRFLOW__CORE__EXECUTOR`` in docker-compose.yaml, so a DAG that
parses here parses there), ``operators.default_queue`` set to ``small`` (so
``hello_world`` resolves to the same class it lands on at run time),
AIRFLOW_HOME on a throwaway dir, and ``dags/`` on ``sys.path`` (so ``from
<project>.common.greetings import ...`` resolves from a DAG file and from the
per-project greetings tests alike).

No container needed: if ``apache-airflow`` is not importable the ``dagbag``
fixture (and everything downstream of it) is SKIPPED rather than erroring,
so a bare ``pip install pytest && pytest`` still runs the container-free
subset -- the per-project ``common.greetings`` unit tests and the ``dags/``
<-> ``tests/`` layout guard. Run ``make test`` for the full suite; it uses
the stack's own image, which already has Airflow.

tests/ sits beside dags/, not inside it, so the dag processor never sees
these files: docker-compose.yaml mounts only ``./dags``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# tests/ sits in compose/, next to dags/. In the `make test` container both are
# mounted under /opt/airflow, so COMPOSE_DIR resolves to /opt/airflow there.
TESTS_DIR = Path(__file__).resolve().parent
COMPOSE_DIR = TESTS_DIR.parent
DAGS_DIR = COMPOSE_DIR / "dags"

_NON_PROJECT_DIRS = {"__pycache__"}

try:
    _HAS_AIRFLOW = importlib.util.find_spec("airflow") is not None
except (ImportError, ValueError):  # pragma: no cover - defensive
    _HAS_AIRFLOW = False


# --- pre-import environment (must run before any `import airflow`) ----------
sys.path.insert(0, str(DAGS_DIR))

os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-test-home-"))
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
os.environ.setdefault("AIRFLOW__CORE__DAGS_FOLDER", str(DAGS_DIR))
os.environ.setdefault("AIRFLOW__CORE__EXECUTOR", "CeleryExecutor")
os.environ.setdefault("AIRFLOW__OPERATORS__DEFAULT_QUEUE", "small")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")

import pytest  # noqa: E402  (must follow the env setup above)


# --- pure-Python helpers (no Airflow import) -------------------------------
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


# --- fixtures -------------------------------------------------------------
def _format_import_errors(errors: dict) -> str:
    lines = ["DagBag import errors:"]
    for path, msg in errors.items():
        last = (msg or "").strip().splitlines()
        lines.append(f"  {path}\n    {last[-1] if last else '<no message>'}")
    return "\n".join(lines)


@pytest.fixture(scope="session")
def dagbag():
    """All of dags/ parsed once per session (raw -- import errors NOT asserted).

    Skips the whole DagBag-dependent slice of the suite when Airflow is not
    installed, so `pytest` runs container-free against a bare environment.
    """
    if not _HAS_AIRFLOW:
        pytest.skip(
            "apache-airflow not installed -- run `make test`, which runs this "
            "suite inside the stack's own image"
        )
    from airflow.models import DagBag

    # No include_examples kwarg in Airflow 3.x -- DagBag.__init__ dropped it;
    # example DAGs are a separate bundle now and are kept out by
    # AIRFLOW__CORE__LOAD_EXAMPLES above plus the explicit dag_folder.
    return DagBag(dag_folder=str(DAGS_DIR))


@pytest.fixture(scope="session")
def dags(dagbag):
    """{dag_id: DAG} across every project, and a hard stop on any import error."""
    assert not dagbag.import_errors, _format_import_errors(dagbag.import_errors)
    return dagbag.dags
