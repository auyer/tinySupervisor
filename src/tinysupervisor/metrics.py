"""Prometheus metrics for the supervisor."""

from prometheus_client import CollectorRegistry, Counter, Gauge

from tinysupervisor.state import TaskEntry
from tinysupervisor.states import RUNNING_STATES, ProcessState


class Metrics:
    """Holds the Prometheus registry and the gauges/counters for tasks."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.total_tasks = Gauge(
            "tinysupervisor_total_tasks",
            "Total number of registered tasks",
            registry=self.registry,
        )
        self.active_tasks = Gauge(
            "tinysupervisor_active_tasks",
            "Number of currently active (running) tasks",
            registry=self.registry,
        )
        self.sleeping_tasks = Gauge(
            "tinysupervisor_sleeping_tasks",
            "Number of sleeping (waiting) tasks",
            registry=self.registry,
        )
        self.completed_tasks = Gauge(
            "tinysupervisor_completed_tasks",
            "Number of completed tasks",
            registry=self.registry,
        )
        self.errors = Counter(
            "tinysupervisor_errors_total",
            "Total number of task errors",
            registry=self.registry,
        )

    def update(self, entries: dict[str, TaskEntry]) -> None:
        total = len(entries)
        active = sum(1 for e in entries.values() if e.state in RUNNING_STATES)
        sleeping = sum(1 for e in entries.values() if e.state is ProcessState.WAITING)
        completed = sum(
            1 for e in entries.values() if e.state is ProcessState.COMPLETED
        )
        self.total_tasks.set(total)
        self.active_tasks.set(active)
        self.sleeping_tasks.set(sleeping)
        self.completed_tasks.set(completed)

    def record_error(self) -> None:
        self.errors.inc()
