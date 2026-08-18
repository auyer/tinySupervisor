"""Logger for tinySupervisor with verbosity levels."""

import logging
import sys
from enum import StrEnum


class Verbosity(StrEnum):
    """Logging verbosity level."""

    SILENT = "silent"
    INFO = "info"
    DEBUG = "debug"


_LEVELS = {
    Verbosity.SILENT: logging.CRITICAL + 10,
    Verbosity.INFO: logging.INFO,
    Verbosity.DEBUG: logging.DEBUG,
}


class Logger:
    """Thread-safe logger that writes to stdout.

    Parameters
    ----------
    verbosity:
        ``"silent"`` suppresses all output, ``"info"`` shows task start/finish,
        ``"debug"`` shows all state transitions.  Accepts :class:`Verbosity`
        enum members or plain strings.
    """

    def __init__(self, verbosity: Verbosity | str = Verbosity.INFO) -> None:
        self.verbosity = Verbosity(verbosity)
        self._logger = logging.getLogger("tinysupervisor")
        self._logger.handlers.clear()
        self._logger.setLevel(_LEVELS[self.verbosity])
        self._logger.propagate = False
        if self.verbosity is not Verbosity.SILENT:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("[tinysupervisor] %(message)s"))
            self._logger.addHandler(handler)

    def info(self, message: str) -> None:
        """Log at INFO level (task starts and finishes)."""
        self._logger.info(message)

    def debug(self, message: str) -> None:
        """Log at DEBUG level (state transitions)."""
        self._logger.debug(message)
