"""Progress uses the same deadlines and process ownership as other FFmpeg runs."""

import subprocess
import sys
import threading

import pytest

from kinocut.errors import ProcessingError
from kinocut.ffmpeg_progress import run_progress


@pytest.mark.parametrize(("environment", "override", "expected"), [("0.2", None, "0.2"), ("30", 0.3, "0.3")])
def test_timeout_policy_reaps_progress_process(monkeypatch, environment, override, expected):
    children = []
    popen = subprocess.Popen

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setenv("KINOCUT_FFMPEG_TIMEOUT", environment)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(ProcessingError) as error:
        run_progress([sys.executable, "-c", "import time; time.sleep(2)"], 1, lambda _: None, float, timeout=override)

    assert str(error.value).endswith(f"FFmpeg command timed out after {expected}s")
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stderr.closed
    assert {thread.ident for thread in threading.enumerate()} == before


def test_callback_timeout_expired_is_preserved_after_cleanup(monkeypatch):
    children = []
    popen = subprocess.Popen

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    before = {thread.ident for thread in threading.enumerate()}
    callback_timeout = subprocess.TimeoutExpired("external callback", 0.01)

    def failing_callback(_percent: float) -> None:
        raise callback_timeout

    script = "import sys, time; sys.stderr.write('time=00:00:01.00\\n'); sys.stderr.flush(); time.sleep(5)"
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        run_progress(
            [sys.executable, "-c", script],
            10.0,
            failing_callback,
            lambda ts: float(ts.split(":")[-1]),
            timeout=30.0,
        )

    assert exc.value is callback_timeout
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stderr.closed
    assert {thread.ident for thread in threading.enumerate()} == before
