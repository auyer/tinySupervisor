"""Process state machine and health semantics for tinySupervisor."""

from enum import IntEnum, StrEnum


class ProcessState(IntEnum):
    """The possible states of a supervised process, mirroring the DESIGN document."""

    COMPLETED = 0
    STARTING = 10
    RUNNING = 20
    BACKOFF = 30
    STOPPING = 40
    WAITING = 50
    EXITED = 100
    FATAL = 200
    UNKNOWN = 1000


#: States in which a process is not currently running.
STOPPED_STATES = (
    ProcessState.COMPLETED,
    ProcessState.EXITED,
    ProcessState.FATAL,
    ProcessState.UNKNOWN,
)

#: States in which a process is considered to be running (or starting).
RUNNING_STATES = (ProcessState.STARTING, ProcessState.RUNNING, ProcessState.BACKOFF)


class DesiredState(StrEnum):
    """Coarse desired state used by the health endpoint and reconciler."""

    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"


_ACCEPTABLE_CURRENT: dict[DesiredState, set[ProcessState]] = {
    DesiredState.RUNNING: {ProcessState.STARTING, ProcessState.RUNNING},
    DesiredState.WAITING: {
        ProcessState.WAITING,
        ProcessState.STARTING,
        ProcessState.RUNNING,
    },
    DesiredState.COMPLETED: {ProcessState.COMPLETED},
}


def acceptable_states(desired: DesiredState) -> set[ProcessState]:
    """Return the set of current states considered acceptable for a desired state."""
    return _ACCEPTABLE_CURRENT[desired]


def is_healthy(current: ProcessState, desired: DesiredState) -> bool:
    """Return True if ``current`` satisfies ``desired``."""
    return current in acceptable_states(desired)
