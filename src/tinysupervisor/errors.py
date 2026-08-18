"""Exceptions raised by tinySupervisor."""

class TinySupervisorError(Exception):
    """Base class for all tinySupervisor errors."""

class UnknownDependencyError(TinySupervisorError):
    """Raised when a task depends on an unknown task."""


class CyclicDependencyError(TinySupervisorError):
    """Raised when the dependency graph contains a cycle."""


