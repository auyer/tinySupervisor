"""In-memory registry of tasks, their runtime state and dependencies."""

from dataclasses import dataclass
from threading import RLock

from tinysupervisor.errors import DuplicateTaskError, UnknownDependencyError
from tinysupervisor.graph import DependencyGraph
from tinysupervisor.process import Process
from tinysupervisor.scheduler import parse_duration
from tinysupervisor.states import ProcessState
from tinysupervisor.task import Task


@dataclass
class TaskEntry:
    """Runtime state for a single registered task."""

    task: Task
    state: ProcessState = ProcessState.WAITING
    run_count: int = 0
    started: bool = False
    completed: bool = False
    handle: Process | None = None
    last_start: float = 0.0
    backoff_count: int = 0
    delay_until: float = 0.0
    next_run: float = 0.0
    interval_s: float | None = None
    run_until_count: int | None = None
    run_until_duration: float | None = None
    until_deadline: float | None = None


class State:
    """Thread-safe registry of all tasks and their dependencies."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.entries: dict[str, TaskEntry] = {}
        self.order: list[str] = []
        self.last_registered: str | None = None
        self.graph: DependencyGraph | None = None

    def add(self, task: Task) -> None:
        with self.lock:
            if task.name in self.entries:
                raise DuplicateTaskError(f"task {task.name!r} is already registered")
            for dep in task.depends:
                if dep not in self.entries:
                    raise UnknownDependencyError(
                        f"task {task.name!r} depends on unknown task {dep!r}"
                    )

            entry = TaskEntry(task=task)
            self._apply_schedule(task, entry)

            self.entries[task.name] = entry
            self.order.append(task.name)
            self.last_registered = task.name
            self._rebuild_graph()

    def _apply_schedule(self, task: Task, entry: TaskEntry) -> None:
        if task.kind == "cron":
            interval = getattr(task, "interval", None)
            run_until = getattr(task, "run_until", None)
            entry.interval_s = parse_duration(interval) if interval is not None else 1.0
            if isinstance(run_until, int):
                entry.run_until_count = run_until
            elif isinstance(run_until, str):
                if run_until.isdigit():
                    entry.run_until_count = int(run_until)
                else:
                    entry.run_until_duration = parse_duration(run_until)

    def _rebuild_graph(self) -> None:
        depends = {name: self.entries[name].task.depends for name in self.order}
        self.graph = DependencyGraph(self.order, depends)
