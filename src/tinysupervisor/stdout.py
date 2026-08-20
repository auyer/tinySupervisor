"""Per-thread stdout/stderr redirection for callable task capture.

``contextlib.redirect_stdout`` mutates the process-global ``sys.stdout``, so
two concurrent callable tasks would capture into each other's sinks.  Instead,
callables run under a pair of :class:`_Router` proxies installed as
``sys.stdout``/``sys.stderr``.  Each callable thread registers its own sink
(the thread-local ``_slot``) and the router dispatches on the current thread,
keeping per-task log files separate.

The routers are installed globally while at least one callable is capturing and
restored once the last one finishes, so ``sys.stdout`` stays untouched for
non-task code (and test capture objects) in between.
"""

import contextlib
import io
import sys
import threading
from typing import Any, TextIO

__all__ = ["capture_sink", "is_proxy_stream"]


class _Router(io.TextIOBase):
    """A stdout/stderr proxy that routes writes to the current thread's sink.

    Each callable thread registers its sink via :func:`capture_sink`; the proxy
    writes there, falling back to the real console for any other thread.
    """

    def __init__(self, fallback: io.TextIOBase) -> None:
        self._fallback = fallback

    def _target(self) -> io.TextIOBase:
        sink = getattr(_slot, "sink", None)
        return sink if sink is not None else self._fallback

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        self._target().flush()

    def isatty(self) -> bool:
        target = self._target()
        return target.isatty() if hasattr(target, "isatty") else False

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return getattr(self._target(), "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._target(), "errors", "strict")


def is_proxy_stream(stream: Any) -> bool:
    """Return whether ``stream`` is one of our redirection proxies."""
    return isinstance(stream, _Router)


def _real_stream(primary: Any, alt: Any) -> Any:
    return (
        primary if primary is not None else (alt if alt is not None else io.StringIO())
    )


_slot = threading.local()
_STDOUT_ROUTER = _Router(_real_stream(sys.__stdout__, sys.stderr))
_STDERR_ROUTER = _Router(_real_stream(sys.__stderr__, sys.stdout))

_capture_lock = threading.Lock()
_capture_count = 0
_capture_original_stdout: TextIO | None = None
_capture_original_stderr: TextIO | None = None


@contextlib.contextmanager
def capture_sink(sink: Any):
    """Capture ``sys.stdout``/``sys.stderr`` for the current thread.

    The routers are installed globally for the process (so concurrent tasks
    share them) but restored once the last capturing task finishes, leaving
    ``sys.stdout`` untouched for non-task code in between.
    """
    global _capture_count, _capture_original_stdout, _capture_original_stderr
    with _capture_lock:
        if _capture_count == 0:
            _capture_original_stdout = sys.stdout
            _capture_original_stderr = sys.stderr
            sys.stdout = _STDOUT_ROUTER
            sys.stderr = _STDERR_ROUTER
        _capture_count += 1
    _slot.sink = sink
    try:
        yield
    finally:
        _slot.sink = None
        with _capture_lock:
            _capture_count -= 1
            if _capture_count == 0:
                if sys.stdout is _STDOUT_ROUTER:
                    sys.stdout = _capture_original_stdout
                if sys.stderr is _STDERR_ROUTER:
                    sys.stderr = _capture_original_stderr
