"""Base task definition shared by Job, CronJob and Service."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# str for external commands, callable for python functions
Executable = str | Callable[..., Any]


class DependencyMode(StrEnum):
    """How a task waits on its dependencies."""

    START = "start"
    COMPLETED = "completed"
    RUN_AFTER = "run_after"


@dataclass(kw_only=True)
class Task:
    """A unit of work managed by the supervisor.

    ``command`` and ``executable`` are aliases for the same underlying
    callable (a shell command string or a Python callable). Provide exactly
    one of them.
    """

    kind = "task"

    name: str
    command: Executable | None = None
    executable: Executable | None = None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    depends: list[str] = field(default_factory=list)
    dependency_mode: DependencyMode | str | None = None
    priority: int = 0
    autostart: bool = True
    autorestart: bool = False
    startsecs: float = 1.0
    startretries: int = 3
    context: str | None = None
    observed: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.command is not None and self.executable is not None:
            raise ValueError("provide either 'command' or 'executable', not both")
        if isinstance(self.dependency_mode, str) and self.dependency_mode is not None:
            self.dependency_mode = DependencyMode(self.dependency_mode)

    @property
    def runnable(self) -> Executable | None:
        """The callable or shell command to execute."""
        if self.command is not None:
            return self.command
        return self.executable
