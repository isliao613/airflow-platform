"""What the ``project1`` project ships. Mirrors ``dags/project1/`` and
``chart/files/roles/project1.json``. Scaffold -- one pipeline, one role.
"""

from __future__ import annotations

PROJECT = "project1"

EXPECTED_DAG_IDS = {"project1_pipeline"}

TEAM_DAG_ROLE = {"project1_pipeline": "project1"}

QUEUE_DAG_CLASS: dict[str, str] = {}

NO_ACL_DAG_IDS: set[str] = set()
