# Task Policies

This document explains the interface the reconciler uses to drive tasks, how
the pieces fit together, and how to define new task types ("modes") by
composing policies.

## Why policies exist

A **policy** contains all type-specific behavior.
The reconciler does not need to know what kind of task it is driving:
it calls the same method for every task,and the task's policy decides what to do.

This is why the reconciler is called "dumb" — see `reconciler.py`:

```python
def reconcile(self) -> None:
    now = time.monotonic()
    with self.state.lock:
        for name in self.state.order:
            entry = self.state.entries[name]
            if self._stopping:
                self._reconcile_stop(entry, now)
                continue
            entry.task.policy.reconcile(entry, self, now)
```

## The three building blocks

The interface lives in `tinysupervisor/policy.py` and is split into three
cooperating pieces, so behavior can be mixed and matched by composition.

### 1. `TaskPolicy` — the per-task interface

A policy owns everything the reconciler needs to know about *one* task type.
It is a plain class; tasks hold a reference to it via the `Task.policy` class
attribute (each task subclass assigns its own policy instance).

The policy has one driving entry point and a handful of hooks:

| Member | Purpose |
|---|---|
| `reconcile(entry, ctx, now)` | The generic state machine, written once. The reconciler calls this every heartbeat. |
| `run` | The pluggable `RunModel` component (see below). |
| `should_start(entry, ctx, now)` | Hook: launch the process now, from `WAITING`? |
| `on_success(entry, ctx, now)` | Hook: the process exited with code 0. Complete, or schedule the next run. |
| `should_restart(entry)` | Hook: restart after `EXITED`? (used by supervised runs) |
| `desired(entry, entries)` | Hook: the coarse `DesiredState` for the health endpoint. |
| `apply_schedule(entry)` | Hook: populate schedule fields on the entry at registration time. |
| `edge_mode(task)` | Hook: the dependency-mode label reported in the graph. |

`reconcile()` is the generic state machine. It handles the `WAITING` state
itself (fail fast if a dependency is `FATAL`, otherwise ask `should_start()`),
then delegates the process-running states (`STARTING`, `RUNNING`, `BACKOFF`,
`EXITED`) to the composed `run` model:

```python
def reconcile(self, entry, ctx, now):
    st = entry.state
    if st is ProcessState.WAITING:
        if ctx.deps_failed(entry.task):
            ctx.transition(entry, ProcessState.FATAL)
            ...
            return
        if self.should_start(entry, ctx, now):
            ctx.start(entry, now)
        return
    if st is ProcessState.STARTING:
        self.run.on_starting(entry, ctx, now, self)
    elif st is ProcessState.RUNNING:
        self.run.on_running(entry, ctx, now, self)
    elif st is ProcessState.BACKOFF:
        self.run.on_backoff(entry, ctx, now, self)
    elif st is ProcessState.EXITED:
        self.run.on_exited(entry, ctx, now, self)
```

`TaskPolicy` itself provides job-like defaults (run once, complete on success)
so it can be used directly; the built-in `JobPolicy` is effectively the base.

### 2. `RunModel` — the pluggable run behavior

A `RunModel` is a component a policy composes. It knows how to supervise a
process *once it has been started*, i.e. what to do while in `STARTING`,
`RUNNING`, `BACKOFF` and `EXITED`. It exposes four methods:

- `on_starting(entry, ctx, now, policy)`
- `on_running(entry, ctx, now, policy)`
- `on_backoff(entry, ctx, now, policy)`
- `on_exited(entry, ctx, now, policy)`

Two implementations ship with the library:

- **`OneshotRun`** (default) — for one-shot tasks. The process is started, and
  on the next check, when it is no longer alive, the exit code is evaluated:
  `0` calls `policy.on_success(...)`, anything else transitions to `FATAL`.
  One-shot tasks may run for any length of time; nothing assumes they are
  short, and all execution stays async.
- **`SupervisedRun`** — for long-running tasks (services). It moves
  `STARTING -> RUNNING` after `startsecs`, backs off and retries when a process
  dies too quickly (`BACKOFF`), and restarts on `EXITED` via
  `policy.should_restart(entry)`.

Because the run model is a plain pluggable object, a policy "switches"
behavior by assigning a different `run`:

```python
class ServicePolicy(TaskPolicy):
    run = SupervisedRun()  # swap the run model
    ...
```

### 3. `ReconcileContext` — the primitives a policy needs

A policy never touches the reconciler's internals directly. Instead it is given
a `ReconcileContext` (a `Protocol`) exposing exactly the shared primitives:

- `entries` — the `{name: TaskEntry}` registry.
- `logger` — the `Logger`.
- `start(entry, now)` — spawn the process, mark `STARTING`.
- `transition(entry, new_state)` — change a task's state (with debug logging).
- `deps_failed(task)` — whether any dependency is `FATAL`.

The concrete `Reconciler` implements this protocol, so policies are fully
decoupled from the reconciler and are trivial to unit-test in isolation.

## How a task is wired to a policy

`Task` (in `task.py`) is a `@dataclass(kw_only=True)` carrying the shared
configuration (`name`, `command`/`executable`, `args`, `kwargs`, `depends`,
`wait_for`, `autostart`, `startsecs`, `env`, ...) plus the runtime bookkeeping
`observed` / `observed_starts` used by dependency-driven policies.

It declares a default policy:

```python
@dataclass(kw_only=True)
class Task:
    kind = "task"
    policy = JobPolicy()
    ...
```

Task subclasses are **not** dataclasses; they follow a small constructor
pattern that calls `super().__init__(...)` and assigns their own `policy` class
attribute. For example `Service`:

```python
class Service(Task):
    kind = "service"
    policy = ServicePolicy()

    def __init__(self, name, ..., wait_for="completed", ...):
        super().__init__(name=name, ..., wait_for=wait_for, ...)
```

`kind` is now purely an informational label; no logic branches on it.

The built-in types and their policies:

| Task | `kind` | `policy` | run model |
|---|---|---|---|
| `Job` | `"job"` | `JobPolicy` | `OneshotRun` |
| `Service` | `"service"` | `ServicePolicy` | `SupervisedRun` |
| `CronJob` | `"cron"` | `CronPolicy` | `OneshotRun` |
| `RecurrentJob` | `"recurrent"` | `RecurrentPolicy` | `OneshotRun` |

## Runtime state: `TaskEntry`

Each registered task gets a `TaskEntry` (in `state.py`) that holds the mutable
runtime state a policy reads and writes:

- `state` — the current `ProcessState`.
- `run_count` / `start_count` — how many times the task has finished / started.
- `started`, `completed` — flags.
- `handle` — the underlying `Process`.
- `last_start`, `backoff_count`, `delay_until` — supervised-run bookkeeping.
- `next_run`, `interval_s`, `run_until_count`, `run_until_duration`,
  `until_deadline` — schedule bookkeeping.

Policies read configuration from `entry.task` and state from `entry`.

## Dependency semantics

Dependencies can be activated when the upstream task is in a desired state.
The two current options are:

- `"completed"` — the dependency must have *completed* (default).
- `"start"` — the dependency only needs to have *started*.

`dependencies_ready(task, entries)` encodes this check. Repeating-on-dependency
behavior is not a dependency mode at all: it is the whole point of
`RecurrentJob`, implemented entirely in `RecurrentPolicy` (see below).

## The built-in policies, in brief

- **`JobPolicy`** — one-shot. `should_start` fires once (when `run_count == 0`
  and dependencies are ready); `on_success` completes the task.
- **`ServicePolicy`** — `SupervisedRun`; `should_start` fires once if
  `autostart` and dependencies are ready; `should_restart` reads `autorestart`;
  `desired` is always `RUNNING`.
- **`CronPolicy`** — repeats on an interval. `should_start` fires on the first
  run or when `now >= next_run`; `on_success` records the run and schedules the
  next; `apply_schedule` parses `interval` / `run_until`; it completes when
  `run_until` (count or deadline) is reached.
- **`RecurrentPolicy`** — repeats each time its dependencies reach a trigger
  state. `trigger_mode="after_run"` (default) triggers when every dependency's
  `run_count` advances past the last observed value; `"after_start"` does the
  same for `start_count`. It completes once all dependencies are completed and
  it has caught up with their last event.

## Creating a new mode

There are two levels of extension, from lightest to most involved.

### A. Subclass an existing policy

Override one or two hooks to tweak behavior.

Example — a job that may only run after some wall-clock gate has been opened
(a runtime flag on the task):

```python
from tinysupervisor.policy import JobPolicy
from tinysupervisor.task import Task


class GatedPolicy(JobPolicy):
    def should_start(self, entry, ctx, now):
        if not entry.task.released:
            return False
        return super().should_start(entry, ctx, now)


class GatedJob(Task):
    kind = "gated"
    policy = GatedPolicy()

    def __init__(self, name, released=False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.released = released
```

### B. Write a policy from scratch

Subclass `TaskPolicy`, choose a `run` model, and implement the hooks.

Example — a job that retries a fixed number of times on failure instead of
going straight to `FATAL`:

```python
from tinysupervisor.policy import TaskPolicy, OneshotRun
from tinysupervisor.states import ProcessState, DesiredState
from tinysupervisor.task import Task


class RetryPolicy(TaskPolicy):
    run = OneshotRun()

    def should_start(self, entry, ctx, now):
        # start on first attempt, or again after a failed attempt (while under the limit)
        return entry.run_count < entry.task.max_attempts

    def on_success(self, entry, ctx, now):
        entry.completed = True
        ctx.transition(entry, ProcessState.COMPLETED)
        ctx.logger.info(f"Task '{entry.task.name}' completed")

    # note: OneshotRun calls on_success on exit 0, but on a non-zero exit it
    # transitions to FATAL. To retry on failure you would instead compose a
    # custom RunModel (see below) that returns to WAITING on non-zero exit.

    def desired(self, entry, entries):
        if entry.completed:
            return DesiredState.COMPLETED
        return DesiredState.WAITING


class RetryJob(Task):
    kind = "retry"
    policy = RetryPolicy()

    def __init__(self, name, max_attempts=3, **kwargs):
        super().__init__(name=name, **kwargs)
        self.max_attempts = max_attempts
```

### C. Write a custom `RunModel`

When you need new *process-supervision* semantics (e.g. handling a non-zero
exit differently), implement the `RunModel` protocol and assign it to
`policy.run`. The base `reconcile()` already dispatches to it — no reconciler
changes required.

```python
from tinysupervisor.policy import TaskPolicy, RunModel
from tinysupervisor.states import ProcessState


class RetryingRun:
    """Return to WAITING on non-zero exit so a retry policy can start again."""

    def on_starting(self, entry, ctx, now, policy):
        handle = entry.handle
        if handle is None:
            return
        if not handle.is_alive():
            code = handle.exitcode()
            entry.handle = None
            if code == 0:
                policy.on_success(entry, ctx, now)
            else:
                ctx.transition(entry, ProcessState.WAITING)

    def on_running(self, entry, ctx, now, policy): ...
    def on_backoff(self, entry, ctx, now, policy): ...
    def on_exited(self, entry, ctx, now, policy): ...


class RetryPolicy(TaskPolicy):
    run = RetryingRun()
    # should_start / on_success / desired as in example B
```

### Guidelines

- **Keep policies stateless.** Configuration belongs on the task (`entry.task`),
  runtime state on the entry (`entry`). Policies may be shared across instances.
- **Prefer composing a `RunModel`** over re-implementing `reconcile()`; the
  generic state machine is there to be reused.
- **Implement `desired()`** so the health endpoint reports the task correctly.
- **Implement `apply_schedule()`** only if your mode carries schedule
  parameters (`interval`, `run_until`, ...); the default is a no-op.
- **Implement `edge_mode()`** to control how edges are labelled in the
  dependency graph (`/state` and `graph()`).

## Testing a policy

Because a policy only depends on `ReconcileContext` (not the concrete
`Reconciler`), you can drive it with a real `Reconciler` in a unit test, or
hand it any object satisfying the protocol. See `tests/unit/test_reconciler.py`
for examples of calling `policy.should_start(...)` and `policy.reconcile(...)`
directly.
