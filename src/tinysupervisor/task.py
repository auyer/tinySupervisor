"""Base task definition shared by Job, CronJob and Service."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tinysupervisor.policy import JobPolicy

# str for external commands, callable for python functions
Executable = str | Callable[..., Any]


@dataclass(kw_only=True)
class Task:
    """A unit of work managed by the supervisor.

    ``command`` and ``executable`` are aliases for the same underlying
    callable (a shell command string or a Python callable). Provide exactly
    one of them.

    ``wait_for`` controls when dependencies are considered ready:
    ``"start"`` (as soon as the dependency has started) or ``"completed"``
    (once the dependency completes).
    """

    kind = "task"
    policy = JobPolicy()

    name: str
    command: Executable | None = None
    executable: Executable | None = None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    depends: list[str] = field(default_factory=list)
    wait_for: str = "completed"
    priority: int = 0
    autostart: bool = True
    autorestart: bool = False
    startsecs: float = 1.0
    startretries: int = 3
    context: str | None = None
    env: dict[str, str] | None = None
    observed: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    observed_starts: dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.command is not None and self.executable is not None:
            raise ValueError("provide either 'command' or 'executable', not both")
        if self.wait_for not in ("start", "completed"):
            raise ValueError(
                f"wait_for must be 'start' or 'completed', got {self.wait_for!r}"
            )

    @property
    def runnable(self) -> Executable | None:
        """The callable or shell command to execute."""
        if self.command is not None:
            return self.command
        return self.executable
