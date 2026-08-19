import time

from tinysupervisor.jobs import CronJob, Job, RecurrentJob
from tinysupervisor.logger import Logger, Verbosity
from tinysupervisor.policy import dependencies_ready
from tinysupervisor.reconciler import Reconciler
from tinysupervisor.service import Service
from tinysupervisor.state import State, TaskEntry
from tinysupervisor.states import ProcessState


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
    job = Job(name="x", command="echo", depends=["a"], wait_for="start")
    assert dependencies_ready(job, {"a": entry(started=True)}) is True
    assert dependencies_ready(job, {"a": entry(started=False)}) is False


def test_completed_mode_ready_after_dep_completed():
    job = Job(name="x", command="echo", depends=["a"], wait_for="completed")
    assert dependencies_ready(job, {"a": entry(run_count=1, completed=True)}) is True
    assert dependencies_ready(job, {"a": entry(run_count=1, completed=False)}) is False


def test_invalid_wait_for_raises():
    try:
        Job(name="x", command="echo", wait_for="run_after")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid wait_for")


# -- RecurrentJob: repeating behaviour lives in the policy --------------------


def test_recurrent_after_run_triggers_on_new_dep_run():
    state = State()
    state.add(Job(name="a", command="echo"))
    job = RecurrentJob(name="b", command="echo", depends=["a"])
    state.add(job)
    rec = Reconciler(state, Logger(Verbosity.SILENT))

    with state.lock:
        entry = state.entries["b"]
        entry.task.observed["a"] = 1
        state.entries["a"].run_count = 2
        assert job.policy.should_start(entry, rec, 0.0) is True
        state.entries["a"].run_count = 1
        assert job.policy.should_start(entry, rec, 0.0) is False


def test_recurrent_after_start_triggers_on_new_dep_start():
    state = State()
    state.add(Job(name="a", command="echo"))
    job = RecurrentJob(
        name="b", command="echo", depends=["a"], trigger_mode="after_start"
    )
    state.add(job)
    rec = Reconciler(state, Logger(Verbosity.SILENT))

    with state.lock:
        entry = state.entries["b"]
        entry.task.observed_starts["a"] = 1
        state.entries["a"].start_count = 2
        assert job.policy.should_start(entry, rec, 0.0) is True
        state.entries["a"].start_count = 1
        assert job.policy.should_start(entry, rec, 0.0) is False


def test_recurrent_job_completes_when_dep_completed():
    state = State()
    state.add(Job(name="a", command="echo"))
    job = RecurrentJob(name="b", command="echo", depends=["a"])
    state.add(job)
    rec = Reconciler(state, Logger(Verbosity.SILENT))

    with state.lock:
        state.entries["a"].completed = True
        state.entries["a"].run_count = 1
        entry = state.entries["b"]
        entry.state = ProcessState.WAITING
        entry.run_count = 1
        entry.task.observed["a"] = 1
        job.policy.reconcile(entry, rec, 0.0)
        assert entry.state is ProcessState.COMPLETED
        assert entry.completed is True


def test_recurrent_job_stays_waiting_when_dep_not_completed():
    state = State()
    state.add(Job(name="a", command="echo"))
    job = RecurrentJob(name="b", command="echo", depends=["a"])
    state.add(job)
    rec = Reconciler(state, Logger(Verbosity.SILENT))

    with state.lock:
        state.entries["a"].run_count = 1
        entry = state.entries["b"]
        entry.state = ProcessState.WAITING
        entry.run_count = 1
        entry.task.observed["a"] = 1
        job.policy.reconcile(entry, rec, 0.0)
        assert entry.state is ProcessState.WAITING


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
            wait_for="completed",
        )
    )

    with state.lock:
        state.entries["up"].state = ProcessState.FATAL
        state.entries["down"].state = ProcessState.WAITING

    rec = Reconciler(state, Logger(Verbosity.SILENT))
    with state.lock:
        entry = state.entries["down"]
        entry.task.policy.reconcile(entry, rec, 0.0)

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
            wait_for="completed",
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
            wait_for="completed",
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
            wait_for="completed",
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


# -- log capture: reconciler builds per-run sinks -----------------------------


def test_start_writes_log_to_configured_folder(tmp_path):
    state = State()
    state.add(Job(name="echo", command="echo hello"))
    rec = Reconciler(state, Logger(Verbosity.SILENT), log_folder=str(tmp_path))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        rec.reconcile()
        with state.lock:
            if state.entries["echo"].state is ProcessState.COMPLETED:
                break
        time.sleep(0.05)

    log = tmp_path / "echo" / "1.log"
    assert log.exists()
    assert "hello" in log.read_text()


def test_cron_runs_produce_numbered_log_files(tmp_path):
    state = State()
    state.add(
        CronJob(
            name="tick",
            interval="50ms",
            run_until=3,
            command="echo beat",
        )
    )
    rec = Reconciler(state, Logger(Verbosity.SILENT), log_folder=str(tmp_path))

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        rec.reconcile()
        with state.lock:
            if state.entries["tick"].state is ProcessState.COMPLETED:
                break
        time.sleep(0.02)

    with state.lock:
        assert state.entries["tick"].run_count == 3
    assert (tmp_path / "tick" / "1.log").exists()
    assert (tmp_path / "tick" / "2.log").exists()
    assert (tmp_path / "tick" / "3.log").exists()
    assert "beat" in (tmp_path / "tick" / "3.log").read_text()


def test_task_stream_logs_override_streams_to_console(tmp_path, capsys):
    state = State()
    state.add(
        CronJob(
            name="loud",
            interval="50ms",
            run_until=1,
            command="echo shout",
            stream_logs=False,
        )
    )
    rec = Reconciler(state, Logger(Verbosity.SILENT), log_folder=str(tmp_path))

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        rec.reconcile()
        with state.lock:
            if state.entries["loud"].state is ProcessState.COMPLETED:
                break
        time.sleep(0.02)

    captured = capsys.readouterr()
    assert "[loud] shout" not in captured.out
    assert "shout" in (tmp_path / "loud" / "1.log").read_text()
