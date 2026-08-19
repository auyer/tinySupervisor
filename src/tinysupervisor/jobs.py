"""The Job helpers: Job, CronJob"""

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
        env: dict[str, str] | None = None,
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
            env=env,
        )


            autostart=autostart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
            env=env,
        )
        if len(self.depends) == 0:
            self._logger.warn(
                "a RecurrentJob needs to be dependendt on at least one task, or it will never run"
            )


class CronJob(Task):
    """A job that repeats on an interval, optionally bounded by ``run_until``.

    ``interval`` is a duration (e.g. ``"10s"``) or a number of seconds.
    ``run_until`` is either a duration string (wall-clock limit) or an integer
    (maximum number of runs).
    """

    kind = "cron"

    def __init__(
        self,
        name: str,
        interval: str | float,
        command: Executable | None = None,
        executable: Executable | None = None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        depends: list[str] | None = None,
        dependency_mode: DependencyMode | str | None = None,
        run_until: str | int | None = None,
        priority: int = 0,
        autostart: bool = True,
        startsecs: float = 1.0,
        startretries: int = 3,
        context: str | None = None,
        env: dict[str, str] | None = None,
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
            env=env,
        )
        self.interval: str | int | float = interval
        self.run_until: str | int | None = run_until
