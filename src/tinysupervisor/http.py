"""HTTP endpoints: health checks and Prometheus metrics."""

import json
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NamedTuple, cast

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from tinysupervisor.states import DesiredState, ProcessState, is_healthy


class TaskStatus(NamedTuple):
    """Runtime status of a single task, exposed via the health endpoint."""

    current: ProcessState
    desired: DesiredState
    run_count: int
    completed: bool


class Snapshot(NamedTuple):
    """A point-in-time snapshot of the supervisor's tasks and dependency graph."""

    processes: Mapping[str, TaskStatus]
    graph: dict[str, Any]


SnapshotProvider = Callable[[], Snapshot]


def compute_health(snapshot: Snapshot) -> tuple[bool, dict[str, Any]]:
    """Build the health payload and whether every process is healthy.

    Returns:
        A ``(healthy, payload)`` tuple where ``payload`` has the shape
        ``{"processes": {name: {...}}, "graph": {"nodes": [...], "edges": [...]}}``.
    """
    processes: dict[str, dict[str, Any]] = {}
    healthy = True
    for name, status in snapshot.processes.items():
        processes[name] = {
            "current": status.current.name.lower(),
            "desired": status.desired.value,
            "run_count": status.run_count,
            "completed": status.completed,
        }
        if not is_healthy(status.current, status.desired):
            healthy = False
    return healthy, {"processes": processes, "graph": snapshot.graph}


class SupervisorHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with access to status, graph and metrics providers."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        snapshot: SnapshotProvider,
        registry: CollectorRegistry,
    ) -> None:
        super().__init__(address, HealthCheckRequestHandler)
        self.snapshot = snapshot
        self.registry = registry


class HealthCheckRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self._handle_health()
        elif self.path == "/state":
            self._handle_state()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_error(404)

    def _handle_health(self) -> None:
        server = cast(SupervisorHTTPServer, self.server)
        healthy, _ = compute_health(server.snapshot())
        status = 200 if healthy else 400
        body = ("OK" if healthy else "Unhealthy").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_state(self) -> None:
        server = cast(SupervisorHTTPServer, self.server)
        healthy, payload = compute_health(server.snapshot())
        status = 200 if healthy else 400
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_metrics(self) -> None:
        server = cast(SupervisorHTTPServer, self.server)
        data = generate_latest(server.registry)
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass
