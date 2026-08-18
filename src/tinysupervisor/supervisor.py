"""The Supervisor: registers tasks and drives them to their desired state."""

import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from tinysupervisor.errors import TaskNotFoundError
from tinysupervisor.http import SupervisorHTTPServer
from tinysupervisor.metrics import Metrics
from tinysupervisor.reconciler import Reconciler, desired_state
from tinysupervisor.scheduler import parse_duration
from tinysupervisor.service import Service
from tinysupervisor.state import State
from tinysupervisor.states import DesiredState, ProcessState
from tinysupervisor.task import DependencyMode, Task

_SHUTDOWN_TIMEOUT = 15.0


class Supervisor:
    """Registers tasks and reconciles their state on a heartbeat interval."""

    def __init__(self) -> None:
        self._state = State()
        self._reconciler = Reconciler(self._state)
        self._metrics = Metrics()
        self._http_port = 8081
        self._heartbeat = 1.0
        self._auto_mode: str | None = None
        self._auto_wait_for: str | None = None
        self._stop_event = threading.Event()
        self._httpd: SupervisorHTTPServer | None = None

    # -- configuration ----------------------------------------------------

    def register(
        self,
        obj: Task | Callable[..., Any],
        *,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Task:
        """Register a task (or a bare callable, wrapped as a Service)."""
        if isinstance(obj, Task):
            task = obj
        elif callable(obj):
            task = Service(
                name=getattr(obj, "__name__", "task"),
                executable=obj,
                args=args or [],
                kwargs=kwargs or {},
            )
        else:
            raise TypeError(f"expected a Task or callable, got {type(obj)!r}")

        if (
            self._auto_mode == "register_order"
            and not task.depends
            and self._state.last_registered is not None
        ):
            task.depends = [self._state.last_registered]
            task.dependency_mode = self._auto_dependency_mode()

        self._state.add(task)
        return task

    def auto_dependency_mode(
        self, mode: str = "register_order", wait_for: str = "start"
    ) -> None:
        """Automatically chain sequentially-registered tasks as dependencies."""
        self._auto_mode = mode
        self._auto_wait_for = wait_for

    def set_heartbeat_interval(self, interval: str | float) -> None:
        """Set the reconciler interval (a duration string or seconds)."""
        self._heartbeat = parse_duration(interval)

    def set_http_port(self, port: int) -> None:
        """Set the HTTP server port."""
        self._http_port = port

    def _auto_dependency_mode(self) -> DependencyMode:
        wait_for = self._auto_wait_for or "start"
        if wait_for in ("completed", "complete"):
            return DependencyMode.COMPLETED
        return DependencyMode.START

    # -- introspection ----------------------------------------------------

    def get_task_state(self, name: str) -> ProcessState:
        with self._state.lock:
            entry = self._state.entries.get(name)
            if entry is None:
                raise TaskNotFoundError(f"unknown task {name!r}")
            return entry.state

    def get_run_count(self, name: str) -> int:
        with self._state.lock:
            entry = self._state.entries.get(name)
            if entry is None:
                raise TaskNotFoundError(f"unknown task {name!r}")
            return entry.run_count

    def statuses(self) -> dict[str, tuple[ProcessState, DesiredState]]:
        with self._state.lock:
            return {
                name: (entry.state, desired_state(entry, self._state.entries))
                for name, entry in self._state.entries.items()
            }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start the HTTP server and run the reconciler loop until stopped."""
        self._install_signal_handlers()
        self._prepare_cron_deadlines()

        self._httpd = SupervisorHTTPServer(
            ("", self._http_port),
            statuses=self.statuses,
            registry=self._metrics.registry,
        )
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

        self._run_loop()

    def stop(self) -> None:
        """Request a graceful shutdown (thread-safe)."""
        self._stop_event.set()

    def _prepare_cron_deadlines(self) -> None:
        now = time.monotonic()
        with self._state.lock:
            for entry in self._state.entries.values():
                if entry.run_until_duration is not None:
                    entry.until_deadline = now + entry.run_until_duration

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._reconciler.reconcile()
            self._metrics.update(self._state.entries)
            self._stop_event.wait(self._sleep_interval())

        self._shutdown()

    def _sleep_interval(self) -> float:
        """Time to sleep between reconciles.

        Polls quickly while any task still has work to do; idles at the
        heartbeat interval once every task is terminal.
        """
        with self._state.lock:
            busy = any(
                entry.state not in (ProcessState.COMPLETED, ProcessState.FATAL)
                for entry in self._state.entries.values()
            )
        return min(self._heartbeat, 0.1) if busy else self._heartbeat

    def _shutdown(self) -> None:
        self._reconciler.set_stopping(True)
        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT
        while time.monotonic() < deadline:
            self._reconciler.reconcile()
            self._metrics.update(self._state.entries)
            with self._state.lock:
                if all(
                    e.state is ProcessState.COMPLETED
                    for e in self._state.entries.values()
                ):
                    break
            time.sleep(0.1)

        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()

    def _install_signal_handlers(self) -> None:
        def handle(signum: int, frame: object) -> None:
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handle)
            except ValueError:
                pass


def init_supervisor() -> Supervisor:
    """Create a new Supervisor."""
    return Supervisor()
