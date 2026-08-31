"""What the ``project2`` project ships. Mirrors ``dags/project2/`` and
``chart/files/roles/project2.json``. Scaffold -- one pipeline, one role.
"""

from __future__ import annotations

PROJECT = "project2"

EXPECTED_DAG_IDS = {"project2_pipeline"}

TEAM_DAG_ROLE = {"project2_pipeline": "project2"}

QUEUE_DAG_CLASS: dict[str, str] = {}

NO_ACL_DAG_IDS: set[str] = set()
