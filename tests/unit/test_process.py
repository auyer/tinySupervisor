import os

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


def test_run_command_with_env():
    assert Process.run("echo $MY_VAR", env={"MY_VAR": "hello"}) == ["hello"]


def test_run_callable_with_env():
    def read_env():
        return os.environ.get("MY_VAR")

    result = Process.run(read_env, env={"MY_VAR": "hello"})
    assert result == "hello"


def test_env_none_inherits_parent():
    home = os.environ.get("HOME")
    result = Process.run("echo $HOME")
    assert result == [home]


# -- Process.start() (async) -------------------------------------------------


def test_start_callable_receives_args_and_kwargs():
    received: dict = {}

    def capture(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs

    proc = Process(capture, args=["a", 1], kwargs={"k": "v"})
    proc.start()
    proc.wait(timeout=5)

    assert received["args"] == ("a", 1)
    assert received["kwargs"] == {"k": "v"}


def test_start_callable_with_env_receives_args_and_kwargs():
    received: dict = {}

    def capture(name, **kwargs):
        received["name"] = name
        received["env"] = os.environ.get("MY_VAR")
        received["kwargs"] = kwargs

    proc = Process(capture, args=["hello"], kwargs={"x": 1}, env={"MY_VAR": "world"})
    proc.start()
    proc.wait(timeout=5)

    assert received["name"] == "hello"
    assert received["env"] == "world"
    assert received["kwargs"] == {"x": 1}


def test_start_callable_with_env_sets_and_restores():
    seen: dict = {}

    def capture():
        seen["value"] = os.environ.get("MY_VAR")

    proc = Process(capture, env={"MY_VAR": "hello"})
    proc.start()
    proc.wait(timeout=5)

    assert seen["value"] == "hello"
    assert "MY_VAR" not in os.environ
