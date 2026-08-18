"""The reconciler loop: compare desired state with actual state and act."""

import time
from collections.abc import Mapping

from tinysupervisor.process import ProcessHandle
from tinysupervisor.state import State, TaskEntry
from tinysupervisor.states import DesiredState, ProcessState
from tinysupervisor.task import DependencyMode, Task

_STOP_GRACE = 5.0


def dependencies_ready(task: Task, entries: Mapping[str, TaskEntry]) -> bool:
    """Return True if all of ``task``'s dependencies are satisfied."""
    if not task.depends:
        return True
    mode = task.dependency_mode or DependencyMode.COMPLETED
    for dep in task.depends:
        entry = entries[dep]
        if mode is DependencyMode.START:
            if not entry.started:
                return False
        elif mode is DependencyMode.COMPLETED:
            if not entry.completed:
                return False
        elif mode is DependencyMode.RUN_AFTER and entry.run_count <= task.observed.get(
            dep, 0
        ):
            return False
    return True


def desired_state(entry: TaskEntry, entries: Mapping[str, TaskEntry]) -> DesiredState:
    """Compute the coarse desired state of a task.

    A task that is not yet complete and is still waiting on unsatisfied
    dependencies is considered "waiting" (healthy), rather than overdue.
    """
    kind = entry.task.kind
    if kind == "service":
        return DesiredState.RUNNING
    if entry.completed:
        return DesiredState.COMPLETED
    if kind == "cron":
        return DesiredState.WAITING
    if dependencies_ready(entry.task, entries):
        return DesiredState.COMPLETED
    return DesiredState.WAITING


class Reconciler:
    """Drives tasks toward their desired state each heartbeat."""

    def __init__(self, state: State) -> None:
        self.state = state
        self._stopping = False

    def set_stopping(self, stopping: bool = True) -> None:
        self._stopping = stopping

    def reconcile(self) -> None:
        now = time.monotonic()
        with self.state.lock:
            for name in self.state.order:
                entry = self.state.entries[name]
                if self._stopping:
                    self._reconcile_stop(entry, now)
                    continue
                kind = entry.task.kind
                if kind == "service":
                    self._reconcile_service(entry, now)
                elif kind == "cron":
                    self._reconcile_cron(entry, now)
                else:
                    self._reconcile_job(entry, now)

    # -- helpers ----------------------------------------------------------

    def _start(self, entry: TaskEntry, now: float) -> None:
        task = entry.task
        entry.handle = ProcessHandle(
            task.runnable, task.args, task.kwargs, task.context
        )
        entry.handle.start()
        entry.last_start = now
        entry.started = True
        entry.state = ProcessState.STARTING

    def _finish_run(self, entry: TaskEntry) -> None:
        task = entry.task
        entry.run_count += 1
        for dep in task.depends:
            task.observed[dep] = self.state.entries[dep].run_count
        if task.kind == "job" and task.dependency_mode is DependencyMode.RUN_AFTER:
            entry.state = ProcessState.WAITING
        else:
            entry.completed = True
            entry.state = ProcessState.COMPLETED

    # -- stop -------------------------------------------------------------

    def _reconcile_stop(self, entry: TaskEntry, now: float) -> None:
        st = entry.state
        if st in (ProcessState.COMPLETED, ProcessState.EXITED, ProcessState.FATAL):
            entry.state = ProcessState.COMPLETED
            entry.completed = True
            entry.handle = None
            return
        if st in (
            ProcessState.STARTING,
            ProcessState.RUNNING,
            ProcessState.BACKOFF,
            ProcessState.WAITING,
        ):
            entry.state = ProcessState.STOPPING
            entry.delay_until = now + _STOP_GRACE
            return
        if st == ProcessState.STOPPING:
            handle = entry.handle
            if handle is not None and handle.is_alive():
                if now >= entry.delay_until:
                    handle.terminate(force=True)
            else:
                entry.state = ProcessState.COMPLETED
                entry.completed = True
                entry.handle = None

    # -- service ----------------------------------------------------------

    def _reconcile_service(self, entry: TaskEntry, now: float) -> None:
        task = entry.task
        st = entry.state

        if st == ProcessState.WAITING:
            if (
                entry.run_count == 0
                and task.autostart
                and dependencies_ready(task, self.state.entries)
            ):
                self._start(entry, now)
            return

        if st == ProcessState.STARTING:
            handle = entry.handle
            if handle is None:
                return
            if handle.is_alive():
                if now - entry.last_start >= task.startsecs:
                    entry.state = ProcessState.RUNNING
                    if entry.run_count == 0:
                        entry.run_count += 1
            else:
                entry.handle = None
                if now - entry.last_start < task.startsecs:
                    entry.state = ProcessState.BACKOFF
                    entry.backoff_count += 1
                    entry.delay_until = now + entry.backoff_count
                else:
                    entry.state = ProcessState.EXITED
            return

        if st == ProcessState.RUNNING:
            handle = entry.handle
            if handle is not None and not handle.is_alive():
                entry.handle = None
                entry.state = ProcessState.EXITED
            return

        if st == ProcessState.BACKOFF:
            if entry.backoff_count > task.startretries:
                entry.state = ProcessState.FATAL
            elif now >= entry.delay_until:
                self._start(entry, now)
            return

        if st == ProcessState.EXITED and task.autorestart:
            self._start(entry, now)

    # -- job --------------------------------------------------------------

    def _reconcile_job(self, entry: TaskEntry, now: float) -> None:
        task = entry.task
        st = entry.state

        if st == ProcessState.STARTING:
            handle = entry.handle
            if handle is None:
                return
            if not handle.is_alive():
                code = handle.exitcode()
                entry.handle = None
                if code == 0:
                    self._finish_run(entry)
                else:
                    entry.state = ProcessState.FATAL
            return

        if st == ProcessState.FATAL:
            return

        if not dependencies_ready(task, self.state.entries):
            return

        if task.dependency_mode is DependencyMode.RUN_AFTER:
            if st in (ProcessState.COMPLETED, ProcessState.WAITING):
                self._start(entry, now)
        elif entry.run_count == 0 and st in (
            ProcessState.COMPLETED,
            ProcessState.WAITING,
        ):
            self._start(entry, now)

    # -- cron -------------------------------------------------------------

    def _reconcile_cron(self, entry: TaskEntry, now: float) -> None:
        task = entry.task
        st = entry.state

        if entry.completed:
            return

        if (
            entry.run_until_count is not None
            and entry.run_count >= entry.run_until_count
        ):
            entry.completed = True
            entry.state = ProcessState.COMPLETED
            return
        if entry.until_deadline is not None and now >= entry.until_deadline:
            entry.completed = True
            entry.state = ProcessState.COMPLETED
            return

        if st == ProcessState.STARTING:
            handle = entry.handle
            if handle is None:
                return
            if not handle.is_alive():
                code = handle.exitcode()
                entry.handle = None
                if code == 0:
                    entry.run_count += 1
                    for dep in task.depends:
                        task.observed[dep] = self.state.entries[dep].run_count
                    entry.state = ProcessState.WAITING
                    entry.next_run = now + (entry.interval_s or 1.0)
                else:
                    entry.state = ProcessState.FATAL
            return

        if st == ProcessState.FATAL:
            return

        if not dependencies_ready(task, self.state.entries):
            return

        if entry.run_count == 0:
            if st in (ProcessState.COMPLETED, ProcessState.WAITING):
                self._start(entry, now)
        elif st == ProcessState.WAITING and now >= entry.next_run:
            self._start(entry, now)
