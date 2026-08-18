"""Process execution: running system processes and Python callables."""

import subprocess
import threading
from typing import Any

import psutil

from tinysupervisor.errors import ProcessError
from tinysupervisor.task import Executable


class Process:
    """A process to be executed.

    A ``Process`` wraps either a shell command (string) or a Python callable
    and manages its execution. It is the low-level execution primitive used by
    the supervisor; ``Job``, ``Service`` and ``CronJob`` are declarative task
    types built on top of it.
    """

    def __init__(
        self,
        runnable: Executable | None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: str | None = None,
    ) -> None:
        self.runnable = runnable
        self.args = args or []
        self.kwargs = kwargs or {}
        self.context = context
        self._proc: subprocess.Popen[Any] | None = None
        self._thread: threading.Thread | None = None

    @staticmethod
    def run(
        executable: Executable,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Run ``executable`` synchronously and return its output/result.

        If ``executable`` is a string it is executed as a shell command and
        its stdout lines are returned as a list. If it is a callable, it is
        invoked with ``args``/``kwargs`` and its return value is returned.
        """
        if isinstance(executable, str):
            return Process._run_command(executable)
        if callable(executable):
            return executable(*(args or []), **(kwargs or {}))
        raise TypeError(
            f"expected a command string or callable, got {type(executable)!r}"
        )

    @staticmethod
    def _run_command(command: str) -> list[str]:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise ProcessError(
                f"command {command!r} failed with exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return result.stdout.splitlines()

    def start(self) -> None:
        """Start the process asynchronously (subprocess or background thread)."""
        if self.runnable is None:
            raise ProcessError("no command or callable provided")
        if isinstance(self.runnable, str):
            self._proc = subprocess.Popen(
                self.runnable,
                shell=True,
                cwd=self.context,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif callable(self.runnable):
            self._thread = threading.Thread(
                target=self.runnable,
                args=self.args,
                kwargs=self.kwargs,
                daemon=True,
            )
            self._thread.start()
        else:
            raise TypeError(
                f"expected a command string or callable, got {type(self.runnable)!r}"
            )

    def is_alive(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        if self._thread is not None:
            return self._thread.is_alive()
        return False

    def wait(self, timeout: float | None = None) -> None:
        if self._proc is not None:
            self._proc.wait(timeout)
        if self._thread is not None:
            self._thread.join(timeout)

    def exitcode(self) -> int | None:
        if self._proc is not None:
            return self._proc.poll()
        if self._thread is not None:
            return None if self._thread.is_alive() else 0
        return None

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
