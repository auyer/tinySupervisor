"""Exceptions raised by tinySupervisor."""


class TinySupervisorError(Exception):
    """Base class for all tinySupervisor errors."""


class DuplicateTaskError(TinySupervisorError):
    """Raised when a task with a duplicate name is registered."""


class UnknownDependencyError(TinySupervisorError):
    """Raised when a task depends on an unknown task."""


class CyclicDependencyError(TinySupervisorError):
    """Raised when the dependency graph contains a cycle."""


class TaskNotFoundError(TinySupervisorError):
    """Raised when a task name is not found."""


class ProcessError(TinySupervisorError):
    """Raised when an underlying process fails."""
