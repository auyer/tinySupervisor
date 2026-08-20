"""Process execution: running system processes and Python callables."""

import contextlib
import io
import os
import subprocess
import sys
import threading
from typing import Any, TextIO

import psutil

from tinysupervisor.errors import ProcessError
from tinysupervisor.logsink import LogSink
from tinysupervisor.task import Executable


class _Router(io.TextIOBase):
    """A stdout/stderr proxy that routes writes to the current thread's sink.

    ``contextlib.redirect_stdout`` mutates the process-global ``sys.stdout``,
    so two concurrent callable tasks would capture into each other's sinks.
    This proxy is installed as the redirect target instead of a ``LogSink``:
    each callable thread registers its own sink and the proxy dispatches on the
    current thread, keeping per-task log files separate.
    """

    def __init__(self, fallback: io.TextIOBase) -> None:
        self._fallback = fallback

    def _target(self) -> io.TextIOBase:
        sink = getattr(_slot, "sink", None)
        return sink if sink is not None else self._fallback

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        self._target().flush()

    def isatty(self) -> bool:
        target = self._target()
        return target.isatty() if hasattr(target, "isatty") else False

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return getattr(self._target(), "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._target(), "errors", "strict")


def _real_stream(primary: Any, alt: Any) -> Any:
    return (
        primary if primary is not None else (alt if alt is not None else io.StringIO())
    )


_slot = threading.local()
_STDOUT_ROUTER = _Router(_real_stream(sys.__stdout__, sys.stderr))
_STDERR_ROUTER = _Router(_real_stream(sys.__stderr__, sys.stdout))

_capture_lock = threading.Lock()
_capture_count = 0
_capture_original_stdout: TextIO | None = None
_capture_original_stderr: TextIO | None = None


@contextlib.contextmanager
def _capture_sink(sink: LogSink):
    """Capture ``sys.stdout``/``sys.stderr`` for the current thread.

    The routers are installed globally for the process (so concurrent tasks
    share them) but restored once the last capturing task finishes, leaving
    ``sys.stdout`` untouched for non-task code in between.
    """
    global _capture_count, _capture_original_stdout, _capture_original_stderr
    with _capture_lock:
        if _capture_count == 0:
            _capture_original_stdout = sys.stdout
            _capture_original_stderr = sys.stderr
            sys.stdout = _STDOUT_ROUTER
            sys.stderr = _STDERR_ROUTER
        _capture_count += 1
    _slot.sink = sink
    try:
        yield
    finally:
        _slot.sink = None
        with _capture_lock:
            _capture_count -= 1
            if _capture_count == 0:
                if sys.stdout is _STDOUT_ROUTER:
                    sys.stdout = _capture_original_stdout
                if sys.stderr is _STDERR_ROUTER:
                    sys.stderr = _capture_original_stderr


class Process:
    """A process to be executed.

    A ``Process`` wraps either a shell command (string) or a Python callable
    and manages its execution. It is the low-level execution primitive used by
    the supervisor; ``Job``, ``Service`` and ``CronJob`` are declarative task
    types built on top of it.

    Execution always happens in a separate daemon thread, so it never blocks
    the caller (e.g. the supervisor's reconcile loop). An optional
    :class:`LogSink` captures the output: shell commands are piped through a
    reader thread, and callables have their ``stdout``/``stderr`` redirected to
    the sink.
    """

    def __init__(
        self,
        runnable: Executable | None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.runnable = runnable
        self.args = args or []
        self.kwargs = kwargs or {}
        self.context = context
        self.env = env
        self._proc: subprocess.Popen[Any] | None = None
        self._thread: threading.Thread | None = None
        self._returncode: int | None = None

    @staticmethod
    def run(
        executable: Executable,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
    ) -> Any:
        """Run ``executable`` synchronously and return its output/result.

        If ``executable`` is a string it is executed as a shell command and
        its stdout lines are returned as a list. If it is a callable, it is
        invoked with ``args``/``kwargs`` and its return value is returned.

        ``env`` is an optional dict of environment variables.  When set the
        child process or callable inherits the parent environment with the
        given values overlaid.
        """
        if isinstance(executable, str):
            return Process._run_command(executable, env=env)
        if callable(executable):
            old: dict[str, str | None] | None = None
            if env:
                old = {k: os.environ.get(k) for k in env}
                os.environ.update(env)
            try:
                return executable(*(args or []), **(kwargs or {}))
            finally:
                if old is not None:
                    for k, v in old.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
        raise TypeError(
            f"expected a command string or callable, got {type(executable)!r}"
        )

    @staticmethod
    def _run_command(command: str, env: dict[str, str] | None = None) -> list[str]:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=False, env=env
        )
        if result.returncode != 0:
            raise ProcessError(
                f"command {command!r} failed with exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return result.stdout.splitlines()

    def start(self, sink: LogSink | None = None) -> None:
        """Start the process in a background thread.

        ``sink`` is an optional :class:`LogSink` that captures the task's
        output (files, and optionally the console).
        """
        if self.runnable is None:
            raise ProcessError("no command or callable provided")
        if isinstance(self.runnable, str):
            if sink is None:
                self._thread = threading.Thread(
                    target=self._run_command_devnull, daemon=True
                )
            else:
                self._thread = threading.Thread(
                    target=self._run_command_captured, args=(sink,), daemon=True
                )
        elif callable(self.runnable):
            if sink is None:
                self._thread = threading.Thread(
                    target=self._run_callable,
                    args=(self.runnable, self.args, self.kwargs, self.env),
                    daemon=True,
                )
            else:
                self._thread = threading.Thread(
                    target=self._run_callable_captured,
                    args=(self.runnable, self.args, self.kwargs, self.env, sink),
                    daemon=True,
                )
        else:
            raise TypeError(
                f"expected a command string or callable, got {type(self.runnable)!r}"
            )
        self._thread.start()

    def _run_command_devnull(self) -> None:
        command = self.runnable
        assert isinstance(command, str)
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.context,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self.env,
        )
        self._proc = proc
        self._returncode = proc.wait()

    def _run_command_captured(self, sink: LogSink) -> None:
        command = self.runnable
        assert isinstance(command, str)
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.context,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self.env,
        )
        self._proc = proc
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sink.write(line)
        except Exception:  # noqa: BLE001
            # A failing sink (e.g. a stale console) must not orphan the child.
            proc.terminate()
        finally:
            try:
                self._returncode = proc.wait()
            finally:
                sink.close()

    def _run_callable(
        self,
        fn: Any,
        args: list[Any],
        kwargs: dict[str, Any],
        env: dict[str, str] | None,
    ) -> None:
        try:
            if env is None:
                fn(*args, **kwargs)
                return
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                fn(*args, **kwargs)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        finally:
            self._returncode = 0

    def _run_callable_captured(
        self,
        fn: Any,
        args: list[Any],
        kwargs: dict[str, Any],
        env: dict[str, str] | None,
        sink: LogSink,
    ) -> None:
        def _target() -> None:
            self._run_callable(fn, args, kwargs, env)

        try:
            with _capture_sink(sink):
                _target()
        finally:
            sink.close()

    def is_alive(self) -> bool:
        if self._thread is None:
            return False
        return self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def exitcode(self) -> int | None:
        if self._thread is None:
            return None
        if self._thread.is_alive():
            return None
        return self._returncode

    def terminate(self, force: bool = False) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            process = psutil.Process(self._proc.pid)
            children = process.children(recursive=True)
            for child in children:
                child.kill() if force else child.terminate()
            process.kill() if force else process.terminate()
        except psutil.NoSuchProcess:
            pass
