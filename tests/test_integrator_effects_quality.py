"""Decoded-media regressions for reported visual defects and timing failures."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from kinocut.effects_engine import effect_glow, effect_vignette
from kinocut.engine_advanced_mask import shape_mask
from kinocut.engine_filters import apply_filter
from kinocut.engine_glitch import glitch_macroblocking
from kinocut.engine_probe import probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")


def _ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def _source(tmp_path, name="source", size="160x96", fps=25, color=None):
    path = tmp_path / f"{name}.mp4"
    video = f"color=c={color}:s={size}:r={fps}:d=0.8" if color else f"testsrc2=s={size}:r={fps}:d=0.8"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        video,
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=0.8",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        path,
    )
    return path


def _pixels(path, width=160, height=96, alpha=False):
    raw = _ffmpeg("-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24", "-")
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4 if alpha else 3)


def _frame_count(path):
    hashes = _ffmpeg("-i", path, "-an", "-f", "framemd5", "-").decode()
    return len([line for line in hashes.splitlines() if line and not line.startswith("#")])


@pytest.mark.parametrize("gray", ["0xD8D8D8", "0x808080"])
def test_glow_retains_neutral_chroma(tmp_path, gray):
    source = _source(tmp_path, color=gray)
    output = tmp_path / "glow.mp4"
    effect_glow(str(source), str(output), intensity=0.2)
    before, after = _pixels(source)[48, 80], _pixels(output)[48, 80]
    assert np.ptp(after.astype(int)) <= 3, after
    if gray == "0xD8D8D8":
        assert after.mean() > before.mean() + 3
    else:
        assert abs(after.mean() - before.mean()) <= 3


def test_vignette_darkens_edges_without_color_cast(tmp_path):
    source = _source(tmp_path, color="0xC0C0C0")
    output = tmp_path / "vignette.mp4"
    effect_vignette(str(source), str(output), intensity=0.6)
    pixels = _pixels(output)
    corner, center = pixels[4, 4].astype(int), pixels[48, 80].astype(int)
    assert corner.mean() < center.mean() - 20
    assert np.ptp(corner) <= 3
    assert abs(center.mean() - _pixels(source)[48, 80].mean()) <= 3


@pytest.mark.parametrize("fps", [25, 30])
def test_ken_burns_preserves_default_frame_count_and_duration(tmp_path, fps):
    source = _source(tmp_path, fps=fps)
    output = tmp_path / "ken.mp4"
    apply_filter(str(source), "ken_burns", output_path=str(output))
    before, after = probe(str(source)), probe(str(output))
    assert _frame_count(source) == _frame_count(output) == round(fps * 0.8)
    assert after.fps == pytest.approx(before.fps)
    assert after.duration == pytest.approx(before.duration, abs=0.05)
    assert after.audio_codec is not None
    assert not np.array_equal(_pixels(source), _pixels(output))


@pytest.mark.parametrize("size", ["540x960", "162x90"])
def test_macroblocking_restores_non_multiple_dimensions(tmp_path, size):
    source = _source(tmp_path, size=size)
    output = tmp_path / "blocks.mp4"
    glitch_macroblocking(str(source), str(output))
    before, after = probe(str(source)), probe(str(output))
    assert (after.width, after.height) == (before.width, before.height)
    assert after.duration == pytest.approx(before.duration, abs=0.05)
    assert after.audio_codec is not None


@pytest.mark.parametrize("suffix", ["mov", "mp4"])
@pytest.mark.parametrize("feather", [0, 6])
def test_shape_mask_container_pixels_duration_and_audio(tmp_path, suffix, feather):
    source = _source(tmp_path, color="red", fps=30)
    output = tmp_path / f"masked.{suffix}"
    result = shape_mask(str(source), output_path=str(output), feather=feather)
    info = probe(str(output))
    pixels = _pixels(output, alpha=suffix == "mov")
    assert info.duration == pytest.approx(probe(str(source)).duration, abs=0.05)
    assert info.audio_codec is not None
    assert result.format == suffix
    assert _frame_count(output) == _frame_count(source) == 24
    assert pixels[48, 80, 0] > 230
    if suffix == "mov":
        assert pixels[0, 0, 3] == 0
        assert pixels[48, 80, 3] >= 250
        if feather:
            assert np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255))
    else:
        assert pixels[0, 0, :3].max() < 5


def test_shape_mask_default_selects_alpha_container(tmp_path):
    source = _source(tmp_path, color="red")
    result = shape_mask(str(source))
    assert result.output_path.endswith(".mov")
    assert _pixels(result.output_path, alpha=True)[0, 0, 3] == 0
