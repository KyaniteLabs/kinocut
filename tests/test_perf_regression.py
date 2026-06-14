"""Perf-regression guard for render-heavy effects.

Several glitch effects and transitions were once implemented with per-pixel
FFmpeg filters (`geq`, `scale=...:eval=frame`) that ran 1-8 s/frame and blew the
600s FFmpeg timeout on any real (>=720p, multi-second) clip — while passing the
existing tests, which only exercised a tiny 640x480/3s fixture.

These tests render each at-risk effect on a 720p/2s clip with a wall-clock
`@pytest.mark.timeout`. A healthy native-filter implementation finishes in a few
seconds; a regression back to per-pixel filtering blows the timeout and fails
here — catching the defect class in the PR (not-slow) set instead of at the 600s
FFmpeg timeout. Keep these effects vectorized.
"""

import os
import subprocess

import pytest

from mcp_video.engine_glitch import (
    glitch_datamoshing,
    glitch_scanline_jitter,
    glitch_screen_tearing,
    glitch_turbulent_displacement,
    glitch_vhs_tracking,
)
from mcp_video.transitions_engine import transition_glitch, transition_pixelate

# 720p/2s is large enough to expose a per-pixel-filter perf bomb (it would take
# minutes) yet renders in a couple seconds with the vectorized implementations.
_W, _H, _D = 1280, 720, 2
# Generous bound: healthy renders take ~1-8s; a per-pixel regression takes minutes.
_TIMEOUT_S = 90


def _make_clip(path: str, color: str | None = None) -> None:
    src = (
        f"testsrc2=s={_W}x{_H}:d={_D}:r=30"
        if color is None
        else f"color=c={color}:s={_W}x{_H}:d={_D}:r=30"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", path],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def hd_clip(tmp_path_factory) -> str:
    p = str(tmp_path_factory.mktemp("perf") / "hd.mp4")
    _make_clip(p)
    return p


@pytest.fixture(scope="module")
def hd_clip2(tmp_path_factory) -> str:
    p = str(tmp_path_factory.mktemp("perf2") / "hd2.mp4")
    _make_clip(p, color="blue")
    return p


_GLITCH_EFFECTS = [
    glitch_screen_tearing,
    glitch_turbulent_displacement,
    glitch_scanline_jitter,
    glitch_vhs_tracking,
    glitch_datamoshing,
]


@pytest.mark.timeout(_TIMEOUT_S)
@pytest.mark.parametrize("effect", _GLITCH_EFFECTS, ids=lambda f: f.__name__)
def test_glitch_effect_is_not_a_perf_bomb(effect, hd_clip, tmp_path):
    out = str(tmp_path / "out.mp4")
    effect(hd_clip, out)
    assert os.path.getsize(out) > 0


@pytest.mark.timeout(_TIMEOUT_S)
@pytest.mark.parametrize(
    "transition", [transition_pixelate, transition_glitch], ids=lambda f: f.__name__
)
def test_transition_is_not_a_perf_bomb(transition, hd_clip, hd_clip2, tmp_path):
    out = str(tmp_path / "out.mp4")
    transition(hd_clip, hd_clip2, out)
    assert os.path.getsize(out) > 0
