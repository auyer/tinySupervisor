"""The Service helper: long-running tasks that should stay running."""

from typing import Any

from tinysupervisor.policy import ServicePolicy
from tinysupervisor.task import Executable, Task


class Service(Task):
    """A long-running task that the supervisor keeps alive."""

    kind = "service"
    policy = ServicePolicy()

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
        autorestart: bool = False,
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
            autorestart=autorestart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
            env=env,
        )

    @classmethod
    def new(
        cls,
        command: Executable,
        context: str | None = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> Service:
        """Create a service that runs ``command`` (optionally in ``context``)."""
        service_name = name or (command if isinstance(command, str) else "service")
        return cls(name=service_name, command=command, context=context, **kwargs)
