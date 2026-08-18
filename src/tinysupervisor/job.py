"""The Job helper: tasks that start, run, and finish (success or failure)."""

from typing import Any

from tinysupervisor.task import DependencyMode, Executable, Task


class Job(Task):
    """A one-shot task that runs once and completes (or fails).

    A job may depend on other tasks via ``depends`` and ``dependency_mode``.
    """

    kind = "job"

    def __init__(
        self,
        name: str,
        command: Executable | None = None,
        executable: Executable | None = None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        depends: list[str] | None = None,
        dependency_mode: DependencyMode | str | None = None,
        priority: int = 0,
        autostart: bool = True,
        startsecs: float = 1.0,
        startretries: int = 3,
        context: str | None = None,
    ) -> None:
        super().__init__(
            name=name,
            command=command,
            executable=executable,
            args=args or [],
            kwargs=kwargs or {},
            depends=depends or [],
            dependency_mode=dependency_mode,
            priority=priority,
            autostart=autostart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
        )
