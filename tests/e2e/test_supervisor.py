import json
import os
import signal
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.helpers import wait_until
from tinysupervisor import CronJob, Job, Service, init_supervisor
from tinysupervisor.states import ProcessState

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


class RunningSupervisor:
    def __init__(self, supervisor, port: int):
        self.supervisor = supervisor
        self.port = port
        self.thread = threading.Thread(target=supervisor.start, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.supervisor.stop()
        self.thread.join(timeout=10)

    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health"

    def metrics_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/metrics"


@pytest.mark.e2e
def test_service_reaches_running_and_health_ok():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Service(name="server", command="sleep 30"))

    with RunningSupervisor(sup, port) as running:
        wait_until(
            lambda: sup.get_task_state("server") == ProcessState.RUNNING,
            message="service should reach RUNNING",
        )
        wait_until(
            lambda: (
                get_json(running.health_url())["processes"]["server"]["current"]
                == "running"
            ),
            message="health endpoint should report running",
        )

    assert sup.get_task_state("server") == ProcessState.COMPLETED


@pytest.mark.e2e
def test_job_completes():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="echo", command="echo hello"))

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("echo") == ProcessState.COMPLETED,
            message="job should complete",
        )


@pytest.mark.e2e
def test_dependency_completed_ordering():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="first", command="sleep 0.3"))
    sup.register(
        Job(
            name="second",
            command="echo done",
            depends=["first"],
            dependency_mode="completed",
        )
    )

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("first") == ProcessState.STARTING,
            message="first job should start",
        )
        # while first is still running, second must still be waiting
        assert sup.get_task_state("second") == ProcessState.WAITING
        wait_until(
            lambda: sup.get_task_state("first") == ProcessState.COMPLETED,
            message="first job should complete",
        )
        wait_until(
            lambda: sup.get_task_state("second") == ProcessState.COMPLETED,
            message="second job should complete after first",
        )


@pytest.mark.e2e
def test_cron_fires_and_stops_on_run_count():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(
        CronJob(name="tick", interval="150ms", run_until=3, command="echo tick")
    )

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("tick") == ProcessState.COMPLETED,
            timeout=15,
            message="cron should terminate after run_until count",
        )
    assert sup.get_run_count("tick") == 3


@pytest.mark.e2e
def test_metrics_endpoint():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Service(name="server", command="sleep 30"))

    with RunningSupervisor(sup, port) as running:
        wait_until(
            lambda: sup.get_task_state("server") == ProcessState.RUNNING,
            message="service should reach RUNNING",
        )
        with urllib.request.urlopen(running.metrics_url(), timeout=5) as resp:
            body = resp.read().decode()
        assert "tinysupervisor" in body


@pytest.mark.e2e
def test_health_returns_400_when_desired_running_but_exited():
    port = free_port()
    sup = init_supervisor()
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Service(name="crashy", command="exit 1"))

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("crashy") == ProcessState.FATAL,
            timeout=15,
            message="failing service should end FATAL",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5)
        assert exc.value.code == 400


@pytest.mark.e2e
@pytest.mark.parametrize("example", ["simple.py", "simple_dag.py"])
def test_examples_run(example: str, tmp_path: Path):
    port = free_port()
    env = {
        "TINYSUPERVISOR_HTTP_PORT": str(port),
        "TINYSUPERVISOR_SERVICE_PORT": str(free_port()),
    }

    script = EXAMPLES_DIR / example
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        env={**os.environ, **env},
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    try:

        def healthy():
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2
                ) as resp:
                    return resp.status == 200
            except urllib.error.URLError, OSError:
                return False

        wait_until(
            healthy, timeout=30, message=f"example {example} should become healthy"
        )
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=10)

    out = proc.stdout.read().decode() if proc.stdout else ""
    assert proc.returncode in (0, -15), f"unexpected exit {proc.returncode}: {out}"
