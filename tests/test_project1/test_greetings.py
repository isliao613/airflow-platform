"""Unit tests for dags/project1/common/greetings.py -- project1's own copy of
the shared helper (projects are fully independent, so this is not the same
module as demo's). Pure Python: no Airflow, no DagBag.
"""

from __future__ import annotations

import socket

from project1.common.greetings import where


def test_where_returns_label_with_hostname(capsys):
    result = where("hello from project1")
    assert result == f"hello from project1 on host={socket.gethostname()}"
    assert result in capsys.readouterr().out


def test_where_is_stable_for_a_given_label():
    assert where("x") == where("x")
