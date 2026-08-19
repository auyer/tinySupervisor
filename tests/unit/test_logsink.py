from tinysupervisor.logsink import LogSink


def test_writes_to_file_and_creates_dirs(tmp_path):
    path = tmp_path / "logs" / "task" / "1.log"
    sink = LogSink(path)
    sink.write("hello\n")
    sink.write("world\n")
    sink.close()

    assert path.read_text() == "hello\nworld\n"


def test_without_stream_does_not_echo(tmp_path, capsys):
    path = tmp_path / "task.log"
    sink = LogSink(path, prefix="my_task")
    sink.write("quiet line\n")
    sink.close()

    assert capsys.readouterr().out == ""
    assert path.read_text() == "quiet line\n"


def test_reopening_truncates_file(tmp_path):
    path = tmp_path / "task.log"
    sink = LogSink(path)
    sink.write("first run\n")
    sink.close()

    sink2 = LogSink(path)
    sink2.write("second run\n")
    sink2.close()

    assert path.read_text() == "second run\n"


def test_streams_lines_with_prefix(tmp_path, capsys):
    sink = LogSink(tmp_path / "1.log", prefix="heartbeat", stream=True)
    sink.write("beat\n")
    sink.close()

    captured = capsys.readouterr()
    assert captured.out == "[heartbeat] beat\n"


def test_streams_partial_lines_on_flush(tmp_path, capsys):
    sink = LogSink(tmp_path / "1.log", prefix="job", stream=True)
    sink.write("no newline")
    sink.flush()
    sink.close()

    captured = capsys.readouterr()
    assert captured.out == "[job] no newline\n"


def test_stream_no_prefix_prints_raw(tmp_path, capsys):
    sink = LogSink(tmp_path / "1.log", stream=True)
    sink.write("raw\n")
    sink.close()

    captured = capsys.readouterr()
    assert captured.out == "raw\n"


def test_write_after_close_raises(tmp_path):
    sink = LogSink(tmp_path / "1.log")
    sink.close()
    try:
        sink.write("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError after close")


def test_flush_writes_buffered_text(tmp_path):
    path = tmp_path / "1.log"
    sink = LogSink(path)
    sink.write("line one\n")
    sink.flush()
    assert "line one\n" in path.read_text()


def test_isatty_false(tmp_path):
    sink = LogSink(tmp_path / "1.log")
    assert sink.isatty() is False
    sink.close()


def test_close_is_idempotent(tmp_path):
    sink = LogSink(tmp_path / "1.log")
    sink.close()
    sink.close()
    assert sink.closed is True
