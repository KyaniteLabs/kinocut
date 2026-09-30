"""Actual pixels verify non-normal blend strength and timeline behavior."""

import json
import shutil
import subprocess

import pytest

from kinocut.engine_composite_layers import composite_layers

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="FFmpeg required"
)


def _pixel(video, seconds, x=32, y=32):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(seconds),
            "-i",
            str(video),
            "-vf",
            f"format=rgb24,crop=1:1:{x}:{y}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert len(result.stdout) == 3
    return tuple(result.stdout)


def _render(tmp_path, opacity, positioned=False, timed=False):
    layer = {
        "id": "blend",
        "type": "solid",
        "color": "#808080",
        "blend": "multiply",
        "opacity": opacity,
        "position": {"x": 16 if positioned else 0, "y": 16 if positioned else 0},
    }
    if positioned:
        layer.update(width=32, height=32)
    if timed:
        layer.update(start=0.3, duration=0.3)
    spec = {
        "canvas": {"width": 64, "height": 64, "fps": 10, "duration": 1},
        "layers": [{"id": "base", "type": "solid", "color": "#808080"}, layer],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    output = tmp_path / f"blend-{opacity}-{positioned}-{timed}.mp4"
    composite_layers(str(path), output_path=str(output))
    return output


@pytest.mark.parametrize("positioned", [False, True])
@pytest.mark.parametrize("opacity,expected", [(0, 128), (0.5, 96), (1, 64)])
def test_blend_strength_interpolates_color_without_double_alpha(tmp_path, positioned, opacity, expected):
    output = _render(tmp_path, opacity, positioned)
    assert _pixel(output, 0.4) == pytest.approx((expected,) * 3, abs=5)
    if positioned:
        assert _pixel(output, 0.4, 4, 4) == pytest.approx((128,) * 3, abs=5)


@pytest.mark.parametrize("positioned", [False, True])
def test_blend_window_preserves_base_before_and_after(tmp_path, positioned):
    output = _render(tmp_path, 0.5, positioned, timed=True)
    assert _pixel(output, 0.1) == pytest.approx((128,) * 3, abs=5)
    assert _pixel(output, 0.4) == pytest.approx((96,) * 3, abs=5)
    assert _pixel(output, 0.8) == pytest.approx((128,) * 3, abs=5)


@pytest.mark.parametrize("positioned", [False, True])
def test_timed_video_blend_plays_opening_frames_at_layer_start(tmp_path, positioned):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=64x64:r=10:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=64x64:r=10:d=0.4",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    layer = {
        "id": "clip",
        "type": "video",
        "src": "clip.mp4",
        "blend": "multiply",
        "opacity": 0.5,
        "start": 1,
        "duration": 0.8,
        "position": {"x": 16 if positioned else 0, "y": 16 if positioned else 0},
    }
    if positioned:
        layer.update(width=32, height=32)
    spec = {
        "canvas": {"width": 64, "height": 64, "fps": 10, "duration": 2},
        "layers": [{"id": "base", "type": "solid", "color": "#808080"}, layer],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    output = tmp_path / "timed.mp4"
    composite_layers(str(path), output_path=str(output))
    assert _pixel(output, 0.5) == pytest.approx((128,) * 3, abs=5)
    red, _, blue = _pixel(output, 1.15)
    assert red > 100 and blue < 90
    red, _, blue = _pixel(output, 1.65)
    assert blue > 100 and red < 90


def test_client_color_grade_forwards_explicit_lut(monkeypatch):
    from kinocut import Client, ai_engine

    calls = []
    monkeypatch.setattr(ai_engine, "ai_color_grade", lambda *args, **kwargs: calls.append((args, kwargs)) or "graded")
    assert Client().ai_color_grade("input.mp4", "output.mp4", lut_path="look.cube").output_path == "graded"
    assert calls == [(("input.mp4", "output.mp4", None, "auto"), {"lut_path": "look.cube"})]


def test_video_mask_plays_from_its_layer_start(tmp_path):
    mask = tmp_path / "mask.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:r=10:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=64x64:r=10:d=0.4",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mask),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    spec = {
        "canvas": {"width": 64, "height": 64, "fps": 10, "duration": 2, "background": "#000000"},
        "layers": [{"id": "red", "type": "solid", "color": "#ff0000", "mask": "mask.mp4", "start": 1, "duration": 0.8}],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    output = tmp_path / "masked.mp4"
    composite_layers(str(path), output_path=str(output))
    assert max(_pixel(output, 1.15)) < 30
    red, _, blue = _pixel(output, 1.65)
    assert red > 150 and blue < 50


@pytest.mark.parametrize("positioned", [False, True])
@pytest.mark.parametrize("alpha", [0, 128, 255])
@pytest.mark.parametrize("opacity", [0.5, 1])
def test_rgb_blending_preserves_source_alpha_coverage(tmp_path, positioned, alpha, opacity):
    image = pytest.importorskip("PIL.Image")
    image.new("RGBA", (64, 64), (0, 0, 0, alpha)).save(tmp_path / "alpha.png")
    layer = {
        "id": "alpha",
        "type": "image",
        "src": "alpha.png",
        "blend": "multiply",
        "opacity": opacity,
        "position": {"x": 16 if positioned else 0, "y": 16 if positioned else 0},
    }
    if positioned:
        layer.update(width=32, height=32)
    spec = {
        "canvas": {"width": 64, "height": 64, "fps": 10, "duration": 0.5},
        "layers": [{"id": "base", "type": "solid", "color": "#808080"}, layer],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    output = tmp_path / "alpha.mp4"
    composite_layers(str(path), output_path=str(output))
    expected = 128 * (1 - opacity * alpha / 255)
    assert _pixel(output, 0.2) == pytest.approx((expected,) * 3, abs=5)
