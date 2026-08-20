"""Per-run log capture for tasks.

A ``LogSink`` writes a task's output to a per-run log file and optionally
mirrors it to the main console, prefixing each line with the task name.
"""

import io
import sys
from pathlib import Path
from typing import Any


def _console_stream() -> Any:
    """Return the stream to echo task output to.

    ``contextlib.redirect_stdout`` swaps the process-global ``sys.stdout`` for
    the whole process, so it can be a ``LogSink`` belonging to a *different*
    task.  Never capture that: echo to a sibling sink would recurse into it and
    crash once it is closed.  Otherwise keep whatever ``sys.stdout`` is (e.g. a
    test capture object) so echo still lands where the caller expects.
    """
    console = sys.stdout
    if isinstance(console, LogSink):
        console = sys.__stdout__ if sys.__stdout__ is not None else sys.stderr
    return console


class LogSink(io.TextIOBase):
    """A line-oriented log sink backed by a file.

    The sink writes raw output to ``path`` (creating parent directories) and,
    when ``stream`` is true, echoes each complete line to ``sys.stdout`` with a
    ``[<prefix>] `` prefix so interleaved task output stays readable.

    It is a text file-like object, so it can be used with
    ``contextlib.redirect_stdout`` / ``redirect_stderr`` for callable tasks and
    handed to a reader thread for shell commands.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        prefix: str | None = None,
        stream: bool = False,
    ) -> None:
        self.path = Path(path)
        self.prefix = prefix
        self.stream = stream
        self._console = _console_stream()
        self._file = None
        self._buffer = ""
        self._open()

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", buffering=1)

    def write(self, text: str) -> int:
        """Write ``text`` to the file; echo complete lines to the console."""
        if self._file is None:
            raise ValueError("I/O operation on closed log sink")
        written = self._file.write(text)
        if self.stream:
            self._echo(text)
        return written

    def _echo(self, text: str) -> None:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)

    def _emit(self, line: str) -> None:
        if not line:
            return
        prefix = f"[{self.prefix}] " if self.prefix else ""
        text = f"{prefix}{line}\n"
        try:
            self._console.write(text)
        except ValueError, OSError:
            # Stale or closed console (e.g. a sibling sink that was closed).
            # Fall back to the real stdout rather than crashing the reader thread.
            if sys.__stdout__ is not None:
                sys.__stdout__.write(text)

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()
        if self.stream and self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

    def close(self) -> None:
        if self._file is not None:
            self.flush()
            self._file.close()
            self._file = None
            super().close()

    @property
    def closed(self) -> bool:
        return self._file is None
