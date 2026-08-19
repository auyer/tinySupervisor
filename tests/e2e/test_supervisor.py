import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.helpers import wait_until
from tinysupervisor import CronJob, Job, RecurrentJob, Service, init_supervisor
from tinysupervisor.states import ProcessState

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


def get_json_any(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode())
    except urllib.error.URLError, OSError:
        return None


def _url_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except urllib.error.URLError, OSError:
        return False


def _file_contains(path: Path, text: str) -> bool:
    try:
        return text in path.read_text()
    except OSError:
        return False


def _terminate_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)


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

    def state_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/state"

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
                get_json(running.state_url())["processes"]["server"]["current"]
                == "running"
            ),
            message="state endpoint should report running",
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
            wait_for="completed",
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
    sup = init_supervisor(keep_running=True)
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
def test_simple_dag_run(tmp_path: Path):
    port = free_port()
    env = {
        "TINYSUPERVISOR_HTTP_PORT": str(port),
        "TINYSUPERVISOR_SERVICE_PORT": str(free_port()),
    }

    script = EXAMPLES_DIR / "simple_dag.py"
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

        wait_until(healthy, timeout=30, message="simple_dag.py should become healthy")
    finally:
        _terminate_process_group(proc)

    out = proc.stdout.read().decode() if proc.stdout else ""
    assert proc.returncode in (0, -15), f"unexpected exit {proc.returncode}: {out}"


@pytest.mark.e2e
def test_simple_server_serves_created_file(tmp_path: Path):
    http_port = free_port()
    service_port = free_port()
    file_name = "created_file.txt"
    env = {
        "TINYSUPERVISOR_HTTP_PORT": str(http_port),
        "TINYSUPERVISOR_SERVICE_PORT": str(service_port),
    }

    script = EXAMPLES_DIR / "simple_server.py"
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        env={**os.environ, **env},
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    file_url = f"http://localhost:{service_port}/{file_name}"
    index_path = tmp_path / "index.html"

    try:
        output_dir = tmp_path / "output"
        wait_until(
            lambda: output_dir.is_dir(), timeout=10, message="output dir should exist"
        )

        # 1. create a file inside the "output" folder
        (output_dir / file_name).write_text("created by e2e test")

        # 2. wait one cron interval for index.html to be regenerated
        time.sleep(1)

        # 3. the file is reachable via the http server
        wait_until(
            lambda: _url_reachable(file_url),
            timeout=15,
            message="file should be reachable via the http server",
        )

        # 4. index.html contains the created file name
        wait_until(
            lambda: _file_contains(index_path, file_name),
            timeout=5,
            message="index.html should contain the created file name",
        )

        # 5. stop the process
        _terminate_process_group(proc)

        # 6. the server is offline
        wait_until(
            lambda: not _url_reachable(file_url),
            timeout=10,
            message="http server should be offline after stopping",
        )
    finally:
        _terminate_process_group(proc)

    # 7. tmp_path (including "output" and index.html) is cleaned up by pytest


@pytest.mark.e2e
def test_simple_dag_cron_completed_dependency():
    port = free_port()
    sup = init_supervisor(keep_running=True)
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="started_job", command='echo "started"'))
    sup.register(
        CronJob(
            name="heart_beat",
            interval="150ms",
            run_until=3,
            command='echo "still running"',
            depends=["started_job"],
            wait_for="completed",
        )
    )
    sup.register(
        RecurrentJob(
            name="confirmation",
            command='echo "beat confirmed"',
            depends=["heart_beat"],
        )
    )
    sup.register(
        Job(
            name="done",
            command='echo "done"',
            depends=["heart_beat"],
            wait_for="completed",
        )
    )

    samples: list[dict] = []

    with RunningSupervisor(sup, port):

        def heartbeat_completed() -> bool:
            payload = get_json_any(f"http://127.0.0.1:{port}/state")
            if payload is None:
                return False
            samples.append(payload)
            return payload["processes"]["heart_beat"]["completed"] is True

        wait_until(
            heartbeat_completed,
            timeout=20,
            message="heart_beat should reach run_until and complete",
        )

        before = [
            p for p in samples if p["processes"]["heart_beat"]["completed"] is False
        ]
        assert before, "expected samples before heart_beat completed"
        for payload in before:
            assert payload["processes"]["done"]["run_count"] == 0

        assert samples[-1]["processes"]["heart_beat"]["run_count"] == 3

        def done_ran() -> bool:
            payload = get_json_any(f"http://127.0.0.1:{port}/state")
            return (
                payload is not None and payload["processes"]["done"]["run_count"] == 1
            )

        wait_until(
            done_ran, timeout=10, message="done should run after heart_beat completes"
        )

        def confirmation_count() -> bool:
            payload = get_json_any(f"http://127.0.0.1:{port}/state")
            return (
                payload is not None
                and payload["processes"]["confirmation"]["run_count"] == 3
            )

        wait_until(
            confirmation_count,
            timeout=10,
            message="confirmation should run on each cron run",
        )

        def confirmation_completed() -> bool:
            payload = get_json_any(f"http://127.0.0.1:{port}/state")
            return (
                payload is not None
                and payload["processes"]["confirmation"]["completed"] is True
            )

        wait_until(
            confirmation_completed,
            timeout=10,
            message="confirmation should complete when heart_beat completes",
        )

        final = get_json_any(f"http://127.0.0.1:{port}/state")
        assert final is not None
        assert set(final["graph"]["nodes"]) == {
            "started_job",
            "heart_beat",
            "confirmation",
            "done",
        }
        edges = {(e["from"], e["to"], e["mode"]) for e in final["graph"]["edges"]}
        assert edges == {
            ("started_job", "heart_beat", "completed"),
            ("heart_beat", "confirmation", "run_after"),
            ("heart_beat", "done", "completed"),
        }


@pytest.mark.e2e
def test_supervisor_exits_when_all_complete(tmp_path: Path):
    port = free_port()
    env = {
        "TINYSUPERVISOR_HTTP_PORT": str(port),
        "TINYSUPERVISOR_CRON_INTERVAL": "150ms",
        "TINYSUPERVISOR_CRON_RUN_UNTIL": "1",
    }

    script = EXAMPLES_DIR / "simple_dag.py"
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        env={**os.environ, **env},
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    try:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _terminate_process_group(proc)
            pytest.fail("supervisor did not exit when all tasks completed")

        assert proc.returncode == 0, f"expected exit code 0, got {proc.returncode}"
    finally:
        _terminate_process_group(proc)


@pytest.mark.e2e
def test_supervisor_keeps_running_when_requested():
    port = free_port()
    sup = init_supervisor(keep_running=True)
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="fast", command="echo done"))

    with RunningSupervisor(sup, port) as running:
        wait_until(
            lambda: sup.get_task_state("fast") == ProcessState.COMPLETED,
            message="fast job should complete",
        )
        time.sleep(0.5)
        assert running.thread.is_alive(), "supervisor should still be alive"


@pytest.mark.e2e
def test_job_writes_log_file(tmp_path: Path):
    port = free_port()
    log_folder = tmp_path / "logs"
    sup = init_supervisor(log_folder=str(log_folder))
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="writer", command="echo captured output"))

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("writer") == ProcessState.COMPLETED,
            message="writer job should complete",
        )

    log = log_folder / "writer" / "1.log"
    assert log.is_file(), f"expected log file at {log}"
    assert "captured output" in log.read_text()


@pytest.mark.e2e
def test_cron_logs_per_run(tmp_path: Path):
    port = free_port()
    log_folder = tmp_path / "logs"
    sup = init_supervisor(log_folder=str(log_folder))
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(
        CronJob(name="tick", interval="100ms", run_until=3, command="echo beat")
    )

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("tick") == ProcessState.COMPLETED,
            timeout=15,
            message="cron should complete",
        )

    assert sup.get_run_count("tick") == 3
    for run in (1, 2, 3):
        log = log_folder / "tick" / f"{run}.log"
        assert log.is_file(), f"expected log file at {log}"
        assert "beat" in log.read_text()


@pytest.mark.e2e
def test_stream_logs_prints_to_console(tmp_path: Path, capsys):
    port = free_port()
    log_folder = tmp_path / "logs"
    sup = init_supervisor(log_folder=str(log_folder), stream_logs=True)
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="chatty", command="echo streamed line"))

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("chatty") == ProcessState.COMPLETED,
            message="chatty job should complete",
        )

    out = capsys.readouterr().out
    assert "[chatty] streamed line" in out
    assert "streamed line" in (log_folder / "chatty" / "1.log").read_text()


@pytest.mark.e2e
def test_task_stream_logs_override(tmp_path: Path, capsys):
    port = free_port()
    log_folder = tmp_path / "logs"
    sup = init_supervisor(log_folder=str(log_folder))  # stream disabled globally
    sup.set_http_port(port)
    sup.set_heartbeat_interval("100ms")
    sup.register(Job(name="loud", command="echo shout", stream_logs=True))
    sup.register(Job(name="quiet", command="echo whisper"))

    with RunningSupervisor(sup, port):
        wait_until(
            lambda: sup.get_task_state("quiet") == ProcessState.COMPLETED,
            message="quiet job should complete",
        )

    out = capsys.readouterr().out
    assert "[loud] shout" in out
    assert "[quiet] whisper" not in out
