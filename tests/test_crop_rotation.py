"""crop() works in display pixels: a phone video stored sideways with a rotation is cropped as it is seen."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from kinocut.engine_crop import crop
from kinocut.engine_probe import probe

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg"
)


def _ffmpeg(*args: str) -> str:
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    return done.stderr


@pytest.fixture(params=[90, -90])
def portrait(tmp_path, request):
    # Stored 320x240 with a 90° display rotation, as phones record portrait video: seen as 240x320.
    stored = tmp_path / "stored.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=25:duration=1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(stored),
    )
    video = tmp_path / "portrait.mp4"
    _ffmpeg("-display_rotation", str(request.param), "-i", str(stored), "-c", "copy", str(video))
    info = probe(str(video))
    assert (info.display_width, info.display_height) == (240, 320)
    return str(video)


def _ssim(a: str, b: str) -> float:
    return float(re.search(r"All:([\d.]+)", _ffmpeg("-i", a, "-i", b, "-lavfi", "ssim", "-f", "null", "-")).group(1))


def test_a_crop_as_tall_as_the_upright_picture_is_accepted(portrait, tmp_path):
    out = str(tmp_path / "tall.mp4")
    crop(portrait, width=240, height=300, output_path=out)
    info = probe(out)
    assert (info.display_width, info.display_height) == (240, 300)


def test_the_default_crop_is_centred_on_the_upright_picture(portrait, tmp_path):
    out = str(tmp_path / "centre.mp4")
    crop(portrait, width=200, height=200, output_path=out)
    centre, stored = str(tmp_path / "centre-ref.mp4"), str(tmp_path / "stored-ref.mp4")
    _ffmpeg("-i", portrait, "-vf", "crop=200:200:20:60", "-c:v", "libx264", "-pix_fmt", "yuv420p", centre)
    _ffmpeg("-i", portrait, "-vf", "crop=200:200:60:20", "-c:v", "libx264", "-pix_fmt", "yuv420p", stored)
    assert _ssim(out, centre) > 0.95 > _ssim(out, stored)


def test_crop_percent_uses_the_upright_size(portrait, tmp_path):
    out = str(tmp_path / "half.mp4")
    crop(portrait, crop_percent=50, output_path=out)
    info = probe(out)
    assert (info.display_width, info.display_height) == (120, 160)
