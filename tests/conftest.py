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
    ``import common.greetings`` resolves from a DAG file and from
    test_greetings.py alike.

tests/ sits beside dags/, not inside it, so the Dockerfile's ``COPY dags/``
never picks these files up: they neither ship to the cluster nor get parsed
by the dag processor, and no .airflowignore is needed to keep them out.
"""

from __future__ import annotations

import os
import sys
import tempfile

from dagtest_util import DAGS_DIR

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
    """dags/ parsed once per session (raw -- import errors NOT asserted)."""
    from airflow.models import DagBag

    # No include_examples kwarg in Airflow 3.x -- DagBag.__init__ dropped it;
    # example DAGs are a separate bundle now and are kept out by
    # AIRFLOW__CORE__LOAD_EXAMPLES above plus the explicit dag_folder.
    return DagBag(dag_folder=str(DAGS_DIR))


@pytest.fixture(scope="session")
def dags(dagbag):
    """{dag_id: DAG}, and a hard stop if parsing produced any import error."""
    assert not dagbag.import_errors, _format_import_errors(dagbag.import_errors)
    return dagbag.dags
