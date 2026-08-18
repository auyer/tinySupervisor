from __future__ import annotations

import pytest

from tinysupervisor.errors import ProcessError
from tinysupervisor.process import Process


def test_run_command_returns_stdout_lines():
    assert Process.run("echo hello") == ["hello"]


def test_run_command_multiple_lines():
    assert Process.run("printf 'a\\nb\\n'") == ["a", "b"]


def test_run_callable_returns_result():
    assert Process.run(str.upper, args=["abc"]) == "ABC"


def test_run_callable_with_kwargs():
    assert Process.run(dict, kwargs={"a": 1}) == {"a": 1}


def test_run_command_failure_raises():
    with pytest.raises(ProcessError):
        Process.run("exit 3")
