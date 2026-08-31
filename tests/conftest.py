"""Test bootstrap for the dags/ suite.

Module-level code here runs before any test module imports Airflow, so the
environment the DagBag sees matches the cluster:

  * examples off;
  * the Airflow-3 multi-executor from chart/values.yaml configured, so
    hello_kubernetes' task-level ``executor="KubernetesExecutor"`` resolves
    during parsing instead of raising;
  * AIRFLOW_HOME on a throwaway temp dir (only used when there is no real
    one, e.g. a local venv -- inside the image AIRFLOW_HOME is already set);
  * dags/ on sys.path, the same as the real dag processor, so
    ``from <project>.common.greetings import ...`` resolves from a DAG file
    and from the per-project greetings tests alike.

One DagBag is built over the WHOLE of dags/ (every project) and shared for
the session; ``tests.dagtest_util.dags_in_project`` slices it per project.

No container needed: if ``apache-airflow`` is not importable, the ``dagbag``
fixture (and everything that depends on it) is SKIPPED rather than erroring,
so a bare ``pip install pytest && pytest`` still runs every check that does
not need a DagBag -- the per-project ``common.greetings`` unit tests and the
project<->tests layout guard. Install ``tests/requirements.txt`` (or run
``make test`` in the image) for the full suite.

tests/ sits beside dags/, not inside it, so the Dockerfile's ``COPY dags/``
never picks these files up: they neither ship to the cluster nor get parsed
by the dag processor, and no .airflowignore is needed to keep them out.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

from tests.dagtest_util import DAGS_DIR

try:
    _HAS_AIRFLOW = importlib.util.find_spec("airflow") is not None
except (ImportError, ValueError):  # pragma: no cover - defensive
    _HAS_AIRFLOW = False

sys.path.insert(0, str(DAGS_DIR))

os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-test-home-"))
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
os.environ.setdefault("AIRFLOW__CORE__DAGS_FOLDER", str(DAGS_DIR))
os.environ.setdefault("AIRFLOW__CORE__EXECUTOR", "CeleryExecutor,KubernetesExecutor")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")

import pytest  # noqa: E402  (must follow the env setup above)


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
            "apache-airflow not installed -- run `pip install -r tests/requirements.txt` "
            "(or `make test`) for the DagBag-dependent checks"
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
