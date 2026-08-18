import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import free_port

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

RUNNABLE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _extract_runnable_examples() -> list[tuple[str, str]]:
    text = README.read_text()
    examples: list[tuple[str, str]] = []
    for match in RUNNABLE_RE.finditer(text):
        block = match.group(1)
        lines = block.split("\n", 1)
        if not lines or not lines[0].startswith("# runnable:"):
            continue
        name = lines[0].split(":", 1)[1].strip()
        code = lines[1] if len(lines) > 1 else ""
        examples.append((name, code))
    return examples


EXAMPLES = _extract_runnable_examples()


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


if not EXAMPLES:
    pytest.skip("README has no runnable examples", allow_module_level=True)


@pytest.mark.e2e
@pytest.mark.parametrize(
    "name,code",
    EXAMPLES,
    ids=[name for name, _ in EXAMPLES],
)
def test_readme_example(name: str, code: str, tmp_path: Path) -> None:
    port = free_port()
    script = tmp_path / f"{name}.py"
    script.write_text(code)

    env = {
        **os.environ,
        "TINYSUPERVISOR_HTTP_PORT": str(port),
    }

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    try:
        try:
            stdout, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            stdout = proc.stdout.read() if proc.stdout else b""
            pytest.fail(
                f"README example {name!r} timed out after 30s\n"
                f"stdout: {stdout.decode(errors='replace')}"
            )

        output = stdout.decode(errors="replace") if stdout else ""
        assert proc.returncode == 0, (
            f"README example {name!r} exited with code {proc.returncode}\n"
            f"output: {output}"
        )
    finally:
        _kill_group(proc)
