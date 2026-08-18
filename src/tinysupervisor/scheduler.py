"""Time-interval parsing helpers."""

import re

_UNITS: dict[str, float] = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}

_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")


def parse_duration(value: str | float) -> float:
    """Parse a human-readable duration into seconds.

    Accepts a number (interpreted as seconds) or a string like ``"500ms"``,
    ``"10s"``, ``"1m"``, ``"1min"``, ``"2h"``, or ``"1d"``.

    Args:
        value: The duration to parse.

    Returns:
        The duration expressed in seconds.

    Raises:
        TypeError: If the value is not a string, integer or float.
        ValueError: If a string value cannot be parsed.
    """
    if isinstance(value, bool):
        raise TypeError(f"invalid duration type: {type(value)!r}")

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        raise TypeError(f"invalid duration type: {type(value)!r}")

    match = _PATTERN.match(value)
    if match is None:
        raise ValueError(f"invalid duration: {value!r}")

    number = float(match.group(1))
    unit = match.group(2).lower()

    if unit == "":
        return number

    if unit not in _UNITS:
        raise ValueError(f"invalid duration unit: {unit!r}")

    return number * _UNITS[unit]
