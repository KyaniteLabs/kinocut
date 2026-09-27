"""accurate=True trims seek the input: the same frames as output seeking, without decoding the file up to start."""

from __future__ import annotations

import subprocess

import pytest

from kinocut.engine_edit import trim
from kinocut.ffmpeg_helpers import _build_ffmpeg_cmd

pytestmark = pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=30).returncode != 0, reason="needs ffmpeg"
)


def _ffmpeg(*args: str) -> str:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _frames(path: str) -> list[str]:
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in _ffmpeg("-i", path, "-an", "-f", "framemd5", "-").splitlines()
        if line and not line.startswith("#")
    ]


@pytest.fixture
def numbered(tmp_path):
    # Each frame shows its own number; a keyframe every 2 s, so 5.5 s falls between two of them.
    video = tmp_path / "numbered.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=30:duration=10",
        "-c:v",
        "libx264",
        "-g",
        "60",
        "-pix_fmt",
        "yuv420p",
        str(video),
    )
    return str(video)


@pytest.mark.parametrize("start", [5.5, 2.0, 0.4])
def test_accurate_trim_gives_the_frames_output_seeking_gives(numbered, tmp_path, start):
    reference = str(tmp_path / "reference.mp4")
    _ffmpeg("-i", numbered, "-ss", str(start), "-t", "1.5", *_build_ffmpeg_cmd(output_path=reference))
    fast = str(tmp_path / "fast.mp4")
    trim(numbered, start=start, duration=1.5, output_path=fast, accurate=True)
    assert _frames(fast) == _frames(reference)
