import pytest

from tinysupervisor.scheduler import parse_duration


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10s", 10.0),
        ("500ms", 0.5),
        ("1m", 60.0),
        ("1min", 60.0),
        ("2h", 7200.0),
        ("1d", 86400.0),
        (5, 5.0),
        (2.5, 2.5),
        ("1.5s", 1.5),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["abc", "", "10x", "s"])
def test_parse_duration_invalid(value):
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", [None, object()])
def test_parse_duration_invalid_type(value):
    with pytest.raises(TypeError):
        parse_duration(value)
