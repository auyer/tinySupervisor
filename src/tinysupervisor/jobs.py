"""The Job helpers: Job, RecurrentJob, CronJob"""

import warnings
from typing import Any

from tinysupervisor.policy import CronPolicy, RecurrentPolicy
from tinysupervisor.task import Executable, Task


class Job(Task):
    """A one-shot task that runs once and completes (or fails).

    A job may depend on other tasks via ``depends`` and ``wait_for``.
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
        wait_for: str = "completed",
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
            wait_for=wait_for,
            priority=priority,
            autostart=autostart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
            env=env,
        )


class RecurrentJob(Task):
    """A job that repeats each time its dependencies reach the trigger state.

    ``trigger_mode`` is either ``"after_run"`` (default; runs whenever a
    dependency completes a new run) or ``"after_start"`` (runs whenever a
    dependency starts running).  The job needs at least one dependency, and
    completes once all of its dependencies are completed and it has caught up
    with their last event.

    For example, with ``a`` and ``b`` as two CronJobs::

        c = RecurrentJob(name="c", command="...", depends=["a", "b"])

    ``c`` runs each time both ``a`` and ``b`` have produced a new run.
    """

    kind = "recurrent"
    policy = RecurrentPolicy()

    def __init__(
        self,
        name: str,
        command: Executable | None = None,
        executable: Executable | None = None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        trigger_mode: str | None = "after_run",
        depends: list[str] | None = None,
        wait_for: str = "completed",
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
            wait_for=wait_for,
            priority=priority,
            autostart=autostart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
            env=env,
        )
        self.trigger_mode = trigger_mode or "after_run"
        if self.trigger_mode not in ("after_run", "after_start"):
            raise ValueError(
                f"trigger_mode must be 'after_run' or 'after_start', "
                f"got {self.trigger_mode!r}"
            )
        if len(self.depends) == 0:
            warnings.warn(
                "a RecurrentJob needs to be dependent on at least one task, "
                "or it will never run",
                stacklevel=2,
            )


class CronJob(Task):
    """A job that repeats on an interval, optionally bounded by ``run_until``.

    ``interval`` is a duration (e.g. ``"10s"``) or a number of seconds.
    ``run_until`` is either a duration string (wall-clock limit) or an integer
    (maximum number of runs).
    """

    kind = "cron"
    policy = CronPolicy()

    def __init__(
        self,
        name: str,
        interval: str | float,
        command: Executable | None = None,
        executable: Executable | None = None,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        depends: list[str] | None = None,
        wait_for: str = "completed",
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
            wait_for=wait_for,
            priority=priority,
            autostart=autostart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
            env=env,
        )
        self.interval: str | int | float = interval
        self.run_until: str | int | None = run_until
