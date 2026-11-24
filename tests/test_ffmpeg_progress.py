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
