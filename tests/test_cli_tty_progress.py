"""Progress displays must not hang a real terminal (#776 regression).

Rich's Live display -- used by every ``Progress`` -- replaces ``sys.stdout`` and
``sys.stderr`` with a ``FileProxy`` that forwards writes back into the same
``Console``. ``HomeCollapsingStream`` looked the target stream up on every
write, so it found that proxy, called back into ``Console.print`` and recursed
forever. Non-TTY runs never start the Live display, which is why CI could not
see it; this test drives a child process on a real pty.
"""

from __future__ import annotations

import os
import pty
import select
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PTY_TIMEOUT_SECONDS = 30.0

PROGRESS_CHILD = """
from rich.panel import Panel
from rich.progress import Progress

from kinocut.cli import formatting

console = formatting.console
with Progress(console=console, transient=True) as progress:
    task = progress.add_task("working", total=1)
    console.print(Panel("rendered while live"))
    progress.advance(task)
print("DONE")
"""

HOME_CHILD = """
import os

from rich.panel import Panel
from rich.progress import Progress

from kinocut.cli import formatting

output_path = os.path.join(os.environ["HOME"], "clips", "final_cut.mp4")
console = formatting.console
with Progress(console=console, transient=True) as progress:
    task = progress.add_task("working", total=1)
    console.print(Panel(f"saved to {output_path}"))
    progress.advance(task)
print("DONE")
"""


def _run_on_a_pty(
    tmp_path: Path,
    source: str,
    *,
    timeout: float = PTY_TIMEOUT_SECONDS,
    env_overrides: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    """Run ``source`` with its std streams on a real pty and return (code, output)."""
    script = tmp_path / "tty_child.py"
    script.write_text(source, encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH"))))
    env["TERM"] = "xterm-256color"
    env.update(env_overrides or {})

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=tmp_path,
        env=env,
        start_new_session=True,
    )
    os.close(slave_fd)

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(proc.pid, signal.SIGKILL)
                output = b"".join(chunks).decode("utf-8", "replace")
                raise AssertionError(f"child did not finish within {timeout}s on a real pty; output so far: {output!r}")
            ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.1))
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:  # Linux raises EIO once the slave side closes.
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            elif proc.poll() is not None:
                break
        returncode = proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        os.close(master_fd)

    return returncode, b"".join(chunks).decode("utf-8", "replace")


@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX-only")
def test_progress_panel_on_a_real_tty_does_not_hang(tmp_path):
    returncode, output = _run_on_a_pty(tmp_path, PROGRESS_CHILD)

    assert returncode == 0, output
    assert "DONE" in output
    assert "rendered while live" in output


@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX-only")
def test_progress_on_a_real_tty_still_hides_the_home_directory(tmp_path):
    home = tmp_path / "fakehome"
    home.mkdir()

    returncode, output = _run_on_a_pty(
        tmp_path,
        HOME_CHILD,
        env_overrides={"HOME": str(home), "USERPROFILE": str(home)},
    )

    assert returncode == 0, output
    assert str(home) not in output
    assert "~/clips/final_cut.mp4" in output
