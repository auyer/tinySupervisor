"""The reconciler loop: compare desired state with actual state and act.

The reconciler is deliberately dumb.  Each task carries a policy that knows
how to proceed, so every task type is driven through the same call path:
``entry.task.policy.reconcile(entry, self, now)``.
"""

import time
from collections.abc import Mapping

from tinysupervisor.logger import Logger
from tinysupervisor.policy import ReconcileContext
from tinysupervisor.process import Process
from tinysupervisor.state import State, TaskEntry
from tinysupervisor.states import DesiredState, ProcessState
from tinysupervisor.task import Task

_STOP_GRACE = 5.0


def desired_state(entry: TaskEntry, entries: Mapping[str, TaskEntry]) -> DesiredState:
    """Compute the coarse desired state of a task.

    A task that is not yet complete and is still waiting on unsatisfied
    dependencies is considered "waiting" (healthy), rather than overdue.
    """
    return entry.task.policy.desired(entry, entries)


class Reconciler(ReconcileContext):
    """Drives tasks toward their desired state each heartbeat."""

    def __init__(self, state: State, logger: Logger) -> None:
        self.state = state
        self._logger = logger
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
                entry.task.policy.reconcile(entry, self, now)

    # -- context helpers --------------------------------------------------

    @property
    def entries(self) -> dict[str, TaskEntry]:
        return self.state.entries

    @property
    def logger(self) -> Logger:
        return self._logger

    def start(self, entry: TaskEntry, now: float) -> None:
        task = entry.task
        entry.handle = Process(
            task.runnable, task.args, task.kwargs, task.context, task.env
        )
        entry.handle.start()
        entry.last_start = now
        entry.started = True
        entry.start_count += 1
        self.transition(entry, ProcessState.STARTING)
        if entry.run_count > 0:
            self._logger.info(
                f"Starting task '{task.name}' (run #{entry.run_count + 1})"
            )
        else:
            self._logger.info(f"Starting task '{task.name}'")

    def transition(self, entry: TaskEntry, new_state: ProcessState) -> None:
        old = entry.state
        if old is new_state:
            return
        self._logger.debug(
            f"Task '{entry.task.name}' state: {old.name} -> {new_state.name}"
        )
        entry.state = new_state

    def deps_failed(self, task: Task) -> bool:
        return any(
            self.state.entries[dep].state is ProcessState.FATAL for dep in task.depends
        )

    # -- stop -------------------------------------------------------------

    def _reconcile_stop(self, entry: TaskEntry, now: float) -> None:
        st = entry.state
        if st in (ProcessState.COMPLETED, ProcessState.EXITED, ProcessState.FATAL):
            self.transition(entry, ProcessState.COMPLETED)
            entry.completed = True
            entry.handle = None
            return
        if st in (
            ProcessState.STARTING,
            ProcessState.RUNNING,
            ProcessState.BACKOFF,
            ProcessState.WAITING,
        ):
            self.transition(entry, ProcessState.STOPPING)
            entry.delay_until = now + _STOP_GRACE
            return
        if st == ProcessState.STOPPING:
            handle = entry.handle
            if handle is not None and handle.is_alive():
                if now >= entry.delay_until:
                    handle.terminate(force=True)
            else:
                self.transition(entry, ProcessState.COMPLETED)
                entry.completed = True
                entry.handle = None
                self._logger.info(f"Task '{entry.task.name}' stopped")
