import time

from tinysupervisor.job import Job
from tinysupervisor.logger import Logger, Verbosity
from tinysupervisor.reconciler import Reconciler, dependencies_ready
from tinysupervisor.service import Service
from tinysupervisor.state import State, TaskEntry
from tinysupervisor.states import ProcessState
from tinysupervisor.task import DependencyMode


def entry(
    started: bool = False, run_count: int = 0, completed: bool = False
) -> TaskEntry:
    return TaskEntry(
        task=Job(name="dep", command="echo"),
        started=started,
        run_count=run_count,
        completed=completed,
    )


def test_no_deps_always_ready():
    job = Job(name="x", command="echo")
    assert dependencies_ready(job, {}) is True


def test_start_mode_ready_after_dep_started():
    job = Job(
        name="x", command="echo", depends=["a"], dependency_mode=DependencyMode.START
    )
    assert dependencies_ready(job, {"a": entry(started=True)}) is True
    assert dependencies_ready(job, {"a": entry(started=False)}) is False


def test_completed_mode_ready_after_dep_completed():
    job = Job(
        name="x",
        command="echo",
        depends=["a"],
        dependency_mode=DependencyMode.COMPLETED,
    )
    assert dependencies_ready(job, {"a": entry(run_count=1, completed=True)}) is True
    assert dependencies_ready(job, {"a": entry(run_count=1, completed=False)}) is False


def test_run_after_triggers_on_new_dep_run():
    job = Job(
        name="x",
        command="echo",
        depends=["a"],
        dependency_mode=DependencyMode.RUN_AFTER,
    )
    job.observed["a"] = 1
    assert dependencies_ready(job, {"a": entry(run_count=2)}) is True
    assert dependencies_ready(job, {"a": entry(run_count=1)}) is False


def test_run_after_job_completes_when_dep_completed():
    state = State()
    dep = Job(name="a", command="echo")
    job = Job(
        name="b",
        command="echo",
        depends=["a"],
        dependency_mode=DependencyMode.RUN_AFTER,
    )
    state.add(dep)
    state.add(job)

    with state.lock:
        state.entries["a"].completed = True
        state.entries["a"].run_count = 1
        state.entries["b"].state = ProcessState.WAITING
        state.entries["b"].run_count = 1
        state.entries["b"].task.observed["a"] = 1

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    with state.lock:
        rec._reconcile_job(state.entries["b"], 0.0)
        assert state.entries["b"].state is ProcessState.COMPLETED
        assert state.entries["b"].completed is True


def test_run_after_job_stays_waiting_when_dep_not_completed():
    state = State()
    dep = Job(name="a", command="echo")
    job = Job(
        name="b",
        command="echo",
        depends=["a"],
        dependency_mode=DependencyMode.RUN_AFTER,
    )
    state.add(dep)
    state.add(job)

    with state.lock:
        state.entries["a"].run_count = 1
        state.entries["b"].state = ProcessState.WAITING
        state.entries["b"].run_count = 1
        state.entries["b"].task.observed["a"] = 1

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    with state.lock:
        rec._reconcile_job(state.entries["b"], 0.0)
        assert state.entries["b"].state is ProcessState.WAITING


# -- WAITING -> FATAL when dependency fails ----------------------------------


def test_waiting_job_fails_when_upstream_fatal():
    """Direct logic: upstream set to FATAL, downstream should go FATAL."""
    state = State()
    state.add(Job(name="up", command="echo"))
    state.add(
        Job(
            name="down",
            command="echo",
            depends=["up"],
            dependency_mode=DependencyMode.COMPLETED,
        )
    )

    with state.lock:
        state.entries["up"].state = ProcessState.FATAL
        state.entries["down"].state = ProcessState.WAITING

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    with state.lock:
        rec._reconcile_job(state.entries["down"], 0.0)

    with state.lock:
        assert state.entries["down"].state is ProcessState.FATAL


def test_waiting_job_fails_when_upstream_fatal_reconcile_loop():
    """Real upstream: exit 1 job (never reaches RUNNING) drives downstream to FATAL."""
    state = State()
    state.add(Job(name="up", command="exit 1"))
    state.add(
        Job(
            name="down",
            command="echo",
            depends=["up"],
            dependency_mode=DependencyMode.COMPLETED,
        )
    )

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        rec.reconcile()
        with state.lock:
            if state.entries["up"].state is ProcessState.FATAL:
                break
        time.sleep(0.05)

    with state.lock:
        assert state.entries["up"].state is ProcessState.FATAL
        assert state.entries["down"].state is ProcessState.FATAL


def test_waiting_service_fails_when_upstream_fatal():
    """Upstream Service exits before startsecs with startretries=0 -> FATAL before RUNNING."""
    state = State()
    state.add(Service(name="up", command="exit 1", startsecs=1.0, startretries=0))
    state.add(
        Job(
            name="down",
            command="echo",
            depends=["up"],
            dependency_mode=DependencyMode.COMPLETED,
        )
    )

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        rec.reconcile()
        with state.lock:
            if state.entries["up"].state is ProcessState.FATAL:
                break
        time.sleep(0.05)

    with state.lock:
        assert state.entries["up"].state is ProcessState.FATAL
        assert state.entries["down"].state is ProcessState.FATAL


def test_waiting_job_stays_waiting_while_upstream_running():
    """Negative: upstream not FATAL -> downstream stays WAITING."""
    state = State()
    state.add(Job(name="up", command="sleep 30"))
    state.add(
        Job(
            name="down",
            command="echo",
            depends=["up"],
            dependency_mode=DependencyMode.COMPLETED,
        )
    )

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    for _ in range(5):
        rec.reconcile()
        time.sleep(0.02)

    with state.lock:
        assert state.entries["up"].state in (
            ProcessState.WAITING,
            ProcessState.STARTING,
            ProcessState.RUNNING,
        )
        assert state.entries["down"].state is ProcessState.WAITING

    with state.lock:
        handle = state.entries["up"].handle
    if handle is not None and handle.is_alive():
        handle.terminate(force=True)
