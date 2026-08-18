"""HTTP endpoints: health checks and Prometheus metrics."""

import json
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from tinysupervisor.states import DesiredState, ProcessState, is_healthy

StatusProvider = Callable[[], Mapping[str, tuple[ProcessState, DesiredState]]]


def compute_health(
    processes: Mapping[str, tuple[ProcessState, DesiredState]],
) -> tuple[bool, dict[str, Any]]:
    """Build the health payload and whether every process is healthy.

    Returns:
        A ``(healthy, payload)`` tuple where ``payload`` has the shape
        ``{"processes": {name: {"current": ..., "desired": ...}}}``.
    """
    payload: dict[str, dict[str, str]] = {}
    healthy = True
    for name, (current, desired) in processes.items():
        payload[name] = {"current": current.name.lower(), "desired": desired.value}
        if not is_healthy(current, desired):
            healthy = False
    return healthy, {"processes": payload}


class SupervisorHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with access to status and metrics providers."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        statuses: StatusProvider,
        registry: CollectorRegistry,
    ) -> None:
        super().__init__(address, HealthCheckRequestHandler)
        self.statuses = statuses
        self.registry = registry


class HealthCheckRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_error(404)

    def _handle_health(self) -> None:
        server = cast(SupervisorHTTPServer, self.server)
        healthy, payload = compute_health(server.statuses())
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
