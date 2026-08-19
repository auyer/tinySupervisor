from tinysupervisor.logger import Logger, Verbosity


def _log_output(capsys, verbosity, calls):
    logger = Logger(verbosity)
    for msg in calls:
        logger.info(msg[1]) if msg[0] == "info" else logger.debug(msg[1])
    return capsys.readouterr().out


def test_silent_suppresses_all(capsys):
    output = _log_output(
        capsys,
        Verbosity.SILENT,
        [("info", "hello"), ("debug", "world")],
    )
    assert output == ""


def test_info_shows_info_not_debug(capsys):
    output = _log_output(
        capsys,
        Verbosity.INFO,
        [("info", "started"), ("debug", "transition")],
    )
    assert "[tinysup] started" in output
    assert "transition" not in output


def test_debug_shows_both(capsys):
    output = _log_output(
        capsys,
        Verbosity.DEBUG,
        [("info", "started"), ("debug", "transition")],
    )
    assert "[tinysup] started" in output
    assert "[tinysup] transition" in output


def test_string_alias():
    logger = Logger("silent")
    assert logger.verbosity is Verbosity.SILENT
    logger = Logger("info")
    assert logger.verbosity is Verbosity.INFO
    logger = Logger("debug")
    assert logger.verbosity is Verbosity.DEBUG


def test_default_verbosity():
    logger = Logger()
    assert logger.verbosity is Verbosity.INFO


def test_prefix_present(capsys):
    Logger(Verbosity.SILENT).info("x")
    Logger(Verbosity.DEBUG).debug("y")
    out = capsys.readouterr().out
    assert "[tinysup] y" in out


def test_info_and_debug_use_correct_levels(capsys):
    logger = Logger(Verbosity.DEBUG)
    logger.info("info-msg")
    logger.debug("debug-msg")
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0] == "[tinysup] info-msg"
    assert lines[1] == "[tinysup] debug-msg"
