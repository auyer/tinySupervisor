"""Task policies: the per-task interface the reconciler drives uniformly.

A policy owns everything the reconciler needs to know about a task type.
The reconciler is deliberately dumb: it calls ``policy.reconcile(...)`` for
every task and never branches on task kind.  Policies are composable — the
run model (oneshot vs supervised) is a pluggable component.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from tinysupervisor.scheduler import parse_duration
from tinysupervisor.states import DesiredState, ProcessState

if TYPE_CHECKING:
    from tinysupervisor.logger import Logger
    from tinysupervisor.state import TaskEntry
    from tinysupervisor.task import Task


def dependencies_ready(task: Task, entries: Mapping[str, TaskEntry]) -> bool:
    """Return True if all of ``task``'s dependencies are satisfied."""
    if not task.depends:
        return True
    wait_for = task.wait_for
    for dep in task.depends:
        entry = entries[dep]
        if wait_for == "start":
            if not entry.started:
                return False
        else:
            if not entry.completed:
                return False
    return True


class ReconcileContext(Protocol):
    """The shared primitives a policy needs to drive a task."""

    @property
    def entries(self) -> dict[str, TaskEntry]: ...

    @property
    def logger(self) -> Logger: ...

    def start(self, entry: TaskEntry, now: float) -> None: ...

    def transition(self, entry: TaskEntry, new_state: ProcessState) -> None: ...

    def deps_failed(self, task: Task) -> bool: ...


class RunModel(Protocol):
    """A pluggable run model: how a started process is supervised."""

    def on_starting(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None: ...

    def on_running(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None: ...

    def on_backoff(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None: ...

    def on_exited(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None: ...


class OneshotRun:
    """Run model for one-shot tasks: start, then done when the process exits.

    One-shot tasks may run for any duration; nothing assumes they are short.
    """

    def on_starting(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        handle = entry.handle
        if handle is None:
            return
        if not handle.is_alive():
            code = handle.exitcode()
            entry.handle = None
            if code == 0:
                policy.on_success(entry, ctx, now)
            else:
                ctx.transition(entry, ProcessState.FATAL)
                ctx.logger.info(f"Task '{entry.task.name}' failed")

    def on_running(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        pass

    def on_backoff(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        pass

    def on_exited(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        pass


class SupervisedRun:
    """Run model for long-running tasks (services): startsecs, backoff, restart."""

    def on_starting(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        task = entry.task
        handle = entry.handle
        if handle is None:
            return
        if handle.is_alive():
            if now - entry.last_start >= task.startsecs:
                ctx.transition(entry, ProcessState.RUNNING)
                ctx.logger.info(f"Task '{task.name}' started")
                if entry.run_count == 0:
                    entry.run_count += 1
        else:
            entry.handle = None
            if now - entry.last_start < task.startsecs:
                ctx.transition(entry, ProcessState.BACKOFF)
                entry.backoff_count += 1
                entry.delay_until = now + entry.backoff_count
            else:
                ctx.transition(entry, ProcessState.EXITED)

    def on_running(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        handle = entry.handle
        if handle is not None and not handle.is_alive():
            entry.handle = None
            ctx.transition(entry, ProcessState.EXITED)

    def on_backoff(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        task = entry.task
        if entry.backoff_count > task.startretries:
            ctx.transition(entry, ProcessState.FATAL)
            ctx.logger.info(f"Task '{task.name}' failed")
        elif now >= entry.delay_until:
            ctx.start(entry, now)

    def on_exited(
        self, entry: TaskEntry, ctx: ReconcileContext, now: float, policy: TaskPolicy
    ) -> None:
        if policy.should_restart(entry):
            ctx.start(entry, now)


class TaskPolicy:
    """Default policy: job semantics — run once when dependencies are ready.

    Policies are stateless; configuration lives on the task.  Subclasses swap
    the run model and override hooks instead of re-implementing the machine.
    """

    run: RunModel = OneshotRun()

    def reconcile(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> None:
        """Drive one task one step toward its desired state."""
        st = entry.state
        if st is ProcessState.WAITING:
            if ctx.deps_failed(entry.task):
                ctx.transition(entry, ProcessState.FATAL)
                ctx.logger.info(f"Task '{entry.task.name}' failed")
                return
            if self.should_start(entry, ctx, now):
                ctx.start(entry, now)
            return
        if st is ProcessState.STARTING:
            self.run.on_starting(entry, ctx, now, self)
            return
        if st is ProcessState.RUNNING:
            self.run.on_running(entry, ctx, now, self)
            return
        if st is ProcessState.BACKOFF:
            self.run.on_backoff(entry, ctx, now, self)
            return
        if st is ProcessState.EXITED:
            self.run.on_exited(entry, ctx, now, self)

    # -- hooks -----------------------------------------------------------

    def should_start(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> bool:
        """Return whether to launch the process from WAITING."""
        raise NotImplementedError

    def on_success(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> None:
        """Handle a successful process exit: complete, or schedule the next run."""
        raise NotImplementedError

    def should_restart(self, entry: TaskEntry) -> bool:
        """Return whether to restart a task that exited (used by supervised runs)."""
        return False

    def desired(
        self, entry: TaskEntry, entries: Mapping[str, TaskEntry]
    ) -> DesiredState:
        """The coarse desired state, used by the health endpoint."""
        raise NotImplementedError

    def apply_schedule(self, entry: TaskEntry) -> None:
        """Populate schedule fields on the entry (no-op unless the task is scheduled)."""

    def edge_mode(self, task: Task) -> str:
        """The dependency mode label reported in the graph for ``task``."""
        return task.wait_for

    # -- shared helpers --------------------------------------------------

    def _record_observed(self, task: Task, ctx: ReconcileContext) -> None:
        for dep in task.depends:
            task.observed[dep] = ctx.entries[dep].run_count
            task.observed_starts[dep] = ctx.entries[dep].start_count


class JobPolicy(TaskPolicy):
    """One-shot: start once dependencies are ready, complete on success."""

    def should_start(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> bool:
        if entry.run_count != 0:
            return False
        return dependencies_ready(entry.task, ctx.entries)

    def on_success(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> None:
        task = entry.task
        entry.run_count += 1
        self._record_observed(task, ctx)
        entry.completed = True
        ctx.transition(entry, ProcessState.COMPLETED)
        ctx.logger.info(f"Task '{task.name}' completed")

    def desired(
        self, entry: TaskEntry, entries: Mapping[str, TaskEntry]
    ) -> DesiredState:
        if entry.completed:
            return DesiredState.COMPLETED
        if dependencies_ready(entry.task, entries):
            return DesiredState.COMPLETED
        return DesiredState.WAITING


class ServicePolicy(TaskPolicy):
    """Long-running: supervised run model with autorestart support."""

    run = SupervisedRun()

    def should_start(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> bool:
        task = entry.task
        return (
            entry.run_count == 0
            and task.autostart
            and dependencies_ready(task, ctx.entries)
        )

    def should_restart(self, entry: TaskEntry) -> bool:
        return entry.task.autorestart

    def desired(
        self, entry: TaskEntry, entries: Mapping[str, TaskEntry]
    ) -> DesiredState:
        return DesiredState.RUNNING


class CronPolicy(TaskPolicy):
    """Recurring on an interval, optionally bounded by a run count or deadline."""

    def should_start(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> bool:
        task = entry.task
        if entry.completed:
            return False
        if not dependencies_ready(task, ctx.entries):
            return False
        if self._run_until_reached(entry, now):
            entry.completed = True
            ctx.transition(entry, ProcessState.COMPLETED)
            ctx.logger.info(f"Task '{task.name}' completed")
            return False
        if entry.run_count == 0:
            return True
        return entry.state is ProcessState.WAITING and now >= entry.next_run

    def on_success(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> None:
        task = entry.task
        entry.run_count += 1
        self._record_observed(task, ctx)
        if self._run_until_reached(entry, now):
            entry.completed = True
            ctx.transition(entry, ProcessState.COMPLETED)
            ctx.logger.info(f"Task '{task.name}' completed")
        else:
            ctx.transition(entry, ProcessState.WAITING)
            ctx.logger.info(f"Task '{task.name}' run finished (run #{entry.run_count})")
            entry.next_run = now + (entry.interval_s or 1.0)

    def _run_until_reached(self, entry: TaskEntry, now: float) -> bool:
        count_reached = (
            entry.run_until_count is not None
            and entry.run_count >= entry.run_until_count
        )
        deadline_reached = (
            entry.until_deadline is not None and now >= entry.until_deadline
        )
        return count_reached or deadline_reached

    def apply_schedule(self, entry: TaskEntry) -> None:
        task = entry.task
        interval = getattr(task, "interval", None)
        run_until = getattr(task, "run_until", None)
        entry.interval_s = parse_duration(interval) if interval is not None else 1.0
        if isinstance(run_until, int):
            entry.run_until_count = run_until
        elif isinstance(run_until, str):
            if run_until.isdigit():
                entry.run_until_count = int(run_until)
            else:
                entry.run_until_duration = parse_duration(run_until)

    def desired(
        self, entry: TaskEntry, entries: Mapping[str, TaskEntry]
    ) -> DesiredState:
        return DesiredState.COMPLETED if entry.completed else DesiredState.WAITING


class RecurrentPolicy(TaskPolicy):
    """Repeats each time its dependencies reach the configured trigger state.

    ``after_run`` (default) triggers when every dependency's ``run_count``
    advances; ``after_start`` when every dependency's ``start_count`` advances.
    The task completes once all dependencies are completed and it has caught
    up with their last event.
    """

    def should_start(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> bool:
        task = entry.task
        if entry.completed:
            return False
        if not task.depends:
            return False
        if self._deps_completed(task, ctx) and not self._trigger_pending(task, ctx):
            entry.completed = True
            ctx.transition(entry, ProcessState.COMPLETED)
            ctx.logger.info(f"Task '{task.name}' completed")
            return False
        return self._trigger_pending(task, ctx)

    def _trigger_pending(self, task: Task, ctx: ReconcileContext) -> bool:
        trigger = getattr(task, "trigger_mode", "after_run")
        for dep in task.depends:
            dep_entry = ctx.entries[dep]
            if trigger == "after_start":
                if dep_entry.start_count <= task.observed_starts.get(dep, 0):
                    return False
            elif dep_entry.run_count <= task.observed.get(dep, 0):
                return False
        return True

    def _deps_completed(self, task: Task, ctx: ReconcileContext) -> bool:
        return all(ctx.entries[dep].completed for dep in task.depends)

    def on_success(self, entry: TaskEntry, ctx: ReconcileContext, now: float) -> None:
        task = entry.task
        entry.run_count += 1
        self._record_observed(task, ctx)
        ctx.transition(entry, ProcessState.WAITING)
        ctx.logger.info(f"Task '{task.name}' run finished (run #{entry.run_count})")

    def desired(
        self, entry: TaskEntry, entries: Mapping[str, TaskEntry]
    ) -> DesiredState:
        return DesiredState.COMPLETED if entry.completed else DesiredState.WAITING

    def edge_mode(self, task: Task) -> str:
        return "run_after"
