"""The Service helper: long-running tasks that should stay running."""

from typing import Any

from tinysupervisor.task import DependencyMode, Executable, Task


class Service(Task):
    """A long-running task that the supervisor keeps alive."""

    kind = "service"

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
        autorestart: bool = False,
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
            autorestart=autorestart,
            startsecs=startsecs,
            startretries=startretries,
            context=context,
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

    def start(self) -> None:
        """Imperatively run the service (blocking) without the supervisor registry."""
        from tinysupervisor.process import ProcessHandle

        handle = ProcessHandle(
            runnable=self.runnable,
            args=self.args,
            kwargs=self.kwargs,
            context=self.context,
        )
        handle.start()
        handle.wait()
