"""Unit tests for dags/common/greetings.py -- the shared helper every demo
DAG imports. Pure Python: needs neither Airflow nor a DagBag, so this file
still runs in a bare `pip install pytest` environment.
"""

from __future__ import annotations

import socket

import pytest

from common.greetings import fail, where


def test_where_returns_label_with_hostname(capsys):
    result = where("hello from class=small")
    assert result == f"hello from class=small on host={socket.gethostname()}"
    # it prints exactly what it returns
    assert result in capsys.readouterr().out


def test_where_is_stable_for_a_given_label():
    assert where("x") == where("x")


def test_fail_raises_runtime_error_with_the_given_reason():
    with pytest.raises(RuntimeError, match="boom"):
        fail("boom")


def test_fail_has_a_default_reason():
    with pytest.raises(RuntimeError, match="designed to fail"):
        fail()
