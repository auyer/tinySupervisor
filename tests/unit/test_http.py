from tinysupervisor.http import Snapshot, TaskStatus, compute_health
from tinysupervisor.states import DesiredState, ProcessState


def _status(current: ProcessState, desired: DesiredState) -> TaskStatus:
    return TaskStatus(current=current, desired=desired, run_count=1, completed=True)


def test_health_all_ok():
    healthy, payload = compute_health(
        Snapshot(
            processes={
                "a": _status(ProcessState.RUNNING, DesiredState.RUNNING),
                "b": _status(ProcessState.COMPLETED, DesiredState.COMPLETED),
            },
            graph={"nodes": ["a", "b"], "edges": []},
        )
    )
    assert healthy is True
    assert payload["processes"]["a"] == {
        "current": "running",
        "desired": "running",
        "run_count": 1,
        "completed": True,
    }
    assert payload["graph"] == {"nodes": ["a", "b"], "edges": []}


def test_health_not_ok():
    healthy, _ = compute_health(
        Snapshot(
            processes={
                "a": _status(ProcessState.EXITED, DesiredState.RUNNING),
            },
            graph={"nodes": ["a"], "edges": []},
        )
    )
    assert healthy is False


def test_health_empty():
    healthy, payload = compute_health(
        Snapshot(processes={}, graph={"nodes": [], "edges": []})
    )
    assert healthy is True
    assert payload == {"processes": {}, "graph": {"nodes": [], "edges": []}}
