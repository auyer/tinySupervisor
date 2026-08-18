import pytest

from tinysupervisor.states import DesiredState, ProcessState, is_healthy


def test_state_values():
    assert ProcessState.COMPLETED == 0
    assert ProcessState.STARTING == 10
    assert ProcessState.RUNNING == 20
    assert ProcessState.BACKOFF == 30
    assert ProcessState.STOPPING == 40
    assert ProcessState.WAITING == 50
    assert ProcessState.EXITED == 100
    assert ProcessState.FATAL == 200
    assert ProcessState.UNKNOWN == 1000


@pytest.mark.parametrize(
    ("current", "desired", "healthy"),
    [
        (ProcessState.RUNNING, DesiredState.RUNNING, True),
        (ProcessState.STARTING, DesiredState.RUNNING, True),
        (ProcessState.EXITED, DesiredState.RUNNING, False),
        (ProcessState.FATAL, DesiredState.RUNNING, False),
        (ProcessState.WAITING, DesiredState.WAITING, True),
        (ProcessState.RUNNING, DesiredState.WAITING, True),
        (ProcessState.COMPLETED, DesiredState.COMPLETED, True),
        (ProcessState.COMPLETED, DesiredState.RUNNING, False),
        (ProcessState.RUNNING, DesiredState.COMPLETED, False),
    ],
)
def test_is_healthy(current, desired, healthy):
    assert is_healthy(current, desired) is healthy
