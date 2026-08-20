import io
import os
import sys
import threading
from typing import cast

import pytest

from tinysupervisor.errors import ProcessError
from tinysupervisor.logsink import LogSink
from tinysupervisor.process import Process
from tinysupervisor.stdout import capture_sink


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


# -- Process.start() with a LogSink (log capture) ----------------------------


def test_start_command_captures_output_to_file(tmp_path):
    sink = LogSink(tmp_path / "cmd.log")
    proc = Process("printf 'a\\nb\\n'")
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert proc.exitcode() == 0
    assert tmp_path.joinpath("cmd.log").read_text() == "a\nb\n"


def test_start_command_captures_stderr_into_same_file(tmp_path):
    sink = LogSink(tmp_path / "cmd.log")
    proc = Process("echo out && echo err >&2")
    proc.start(sink=sink)
    proc.wait(timeout=5)

    content = tmp_path.joinpath("cmd.log").read_text()
    assert "out" in content
    assert "err" in content


def test_start_command_captures_nonzero_exit(tmp_path):
    sink = LogSink(tmp_path / "cmd.log")
    proc = Process("echo boom && exit 3")
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert proc.exitcode() == 3
    assert "boom" in tmp_path.joinpath("cmd.log").read_text()


def test_start_callable_captures_print_to_file(tmp_path):
    sink = LogSink(tmp_path / "fn.log")

    def speak():
        print("from function")

    proc = Process(speak)
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert proc.exitcode() == 0
    assert tmp_path.joinpath("fn.log").read_text() == "from function\n"


def test_start_callable_captures_stderr_to_file(tmp_path):
    sink = LogSink(tmp_path / "fn.log")

    def warn():
        print("bad", file=sys.stderr)

    proc = Process(warn)
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert tmp_path.joinpath("fn.log").read_text() == "bad\n"


def test_start_callable_with_env_and_capture(tmp_path):
    sink = LogSink(tmp_path / "fn.log")

    def read_env():
        print(os.environ.get("MY_VAR"))

    proc = Process(read_env, env={"MY_VAR": "hello"})
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert proc.exitcode() == 0
    assert tmp_path.joinpath("fn.log").read_text() == "hello\n"
    assert "MY_VAR" not in os.environ


def test_start_command_streams_to_console(tmp_path, capsys):
    sink = LogSink(tmp_path / "cmd.log", prefix="t", stream=True)
    proc = Process("echo streamed")
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert capsys.readouterr().out == "[t] streamed\n"


def test_start_callable_streams_to_console(tmp_path, capsys):
    sink = LogSink(tmp_path / "fn.log", prefix="t", stream=True)

    def speak():
        print("streamed from fn")

    proc = Process(speak)
    proc.start(sink=sink)
    proc.wait(timeout=5)

    assert capsys.readouterr().out == "[t] streamed from fn\n"


def test_start_without_sink_keeps_callable_exitcode_zero():
    proc = Process(lambda: None)
    proc.start()
    proc.wait(timeout=5)
    assert proc.exitcode() == 0


def test_concurrent_callables_capture_separate_files(tmp_path):
    sink_a = LogSink(tmp_path / "a.log")
    sink_b = LogSink(tmp_path / "b.log")
    barrier = threading.Barrier(2)

    def speak(label):
        barrier.wait(timeout=5)
        for _ in range(20):
            print(label, flush=True)

    proc_a = Process(speak, args=["A"])
    proc_b = Process(speak, args=["B"])
    proc_a.start(sink=sink_a)
    proc_b.start(sink=sink_b)
    proc_a.wait(timeout=5)
    proc_b.wait(timeout=5)

    assert tmp_path.joinpath("a.log").read_text() == "A\n" * 20
    assert tmp_path.joinpath("b.log").read_text() == "B\n" * 20


def test_failing_sink_does_not_orphan_subprocess():
    class BrokenSink:
        def __init__(self):
            self.closed = False

        def write(self, text):
            raise ValueError("boom")

        def close(self):
            self.closed = True

    sink = BrokenSink()
    proc = Process("sleep 0.2 && echo hi")
    proc.start(sink=cast(LogSink, sink))
    proc.wait(timeout=5)

    assert proc.exitcode() is not None
    assert sink.closed is True


def test_callable_sink_built_during_capture_does_not_recurse(tmp_path, monkeypatch):
    fallback = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", fallback)
    holder = LogSink(tmp_path / "holder.log")
    with capture_sink(holder):  # sys.stdout is now the redirection router
        sink_b = LogSink(tmp_path / "b.log", prefix="b", stream=True)

    def speak():
        print("hello")

    proc = Process(speak)
    proc.start(sink=sink_b)
    proc.wait(timeout=5)

    assert tmp_path.joinpath("b.log").read_text() == "hello\n"
    assert "[b] hello\n" in fallback.getvalue()
    holder.close()
