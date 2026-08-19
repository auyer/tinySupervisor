from tinysupervisor.jobs import Job
from tinysupervisor.logger import Verbosity
from tinysupervisor.states import ProcessState
from tinysupervisor.supervisor import Supervisor


def _supervisor_with_entries(**states: ProcessState) -> Supervisor:
    sup = Supervisor(verbosity=Verbosity.SILENT)
    for name, state in states.items():
        sup.register(Job(name=name, command="echo"))
        with sup._state.lock:
            sup._state.entries[name].state = state
    return sup


def test_all_done_empty():
    sup = Supervisor(verbosity=Verbosity.SILENT)
    assert sup._all_done() is True


def test_all_done_all_completed():
    sup = _supervisor_with_entries(a=ProcessState.COMPLETED, b=ProcessState.COMPLETED)
    assert sup._all_done() is True


def test_all_done_all_fatal():
    sup = _supervisor_with_entries(a=ProcessState.FATAL, b=ProcessState.FATAL)
    assert sup._all_done() is True


def test_all_done_mixed_terminal():
    sup = _supervisor_with_entries(a=ProcessState.COMPLETED, b=ProcessState.FATAL)
    assert sup._all_done() is True


def test_all_done_not_all_terminal():
    sup = _supervisor_with_entries(a=ProcessState.WAITING, b=ProcessState.COMPLETED)
    assert sup._all_done() is False


def test_all_done_running():
    sup = _supervisor_with_entries(a=ProcessState.RUNNING)
    assert sup._all_done() is False


def test_keep_running_default_false():
    sup = Supervisor()
    assert sup._keep_running is False


def test_keep_running_true():
    sup = Supervisor(keep_running=True)
    assert sup._keep_running is True
