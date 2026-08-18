from tinysupervisor.job import Job
from tinysupervisor.reconciler import dependencies_ready
from tinysupervisor.state import TaskEntry
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
