from tinysupervisor.http import compute_health
from tinysupervisor.states import DesiredState, ProcessState


def test_health_all_ok():
    healthy, payload = compute_health(
        {
            "a": (ProcessState.RUNNING, DesiredState.RUNNING),
            "b": (ProcessState.COMPLETED, DesiredState.COMPLETED),
        }
    )
    assert healthy is True
    assert payload == {
        "processes": {
            "a": {"current": "running", "desired": "running"},
            "b": {"current": "completed", "desired": "completed"},
        }
    }


def test_health_not_ok():
    healthy, _ = compute_health(
        {
            "a": (ProcessState.EXITED, DesiredState.RUNNING),
        }
    )
    assert healthy is False


def test_health_empty():
    healthy, payload = compute_health({})
    assert healthy is True
    assert payload == {"processes": {}}
