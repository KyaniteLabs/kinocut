"""Regression pins for the 2026-09-24 integrator batch (guillaume-hestia-projekt).

Each test pins a reported defect class from the 15-issue integrator batch so the
fix cannot silently regress:

- #548/#556: merge transitions and the video-filter path (e.g. ``sepia``) must
  emit web-safe ``yuv420p`` instead of inheriting ``yuv444p`` (unplayable in
  many browsers/phones; not concatenable with yuv420p segments).
- #550: ``layout_pip`` must not pass a full ffprobe command to the raw-args
  runner (raised ``ValueError`` on every call since the runner split).
- #553: ``drawtext`` font family names must resolve to a concrete font file —
  the bare ``font=<family>`` option access-violates FFmpeg builds without
  fontconfig (Windows 0xC0000005).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from mcp_video.effects_engine.text import (
    _drawtext_font_option,
    _resolve_font_family_to_file,
    _load_pil_font,
)
from mcp_video.engine_filters import apply_filter
from mcp_video.engine_merge import merge


def _pix_fmt(path: str) -> str:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return out.stdout.strip()


def _make_clip(path: str, seconds: str = "2") -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={seconds}:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            path,
        ],
        capture_output=True,
        timeout=60,
        check=True,
    )


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="requires ffmpeg/ffprobe",
)


def test_merge_with_transition_emits_yuv420p(tmp_path, sample_video):
    result = merge(
        [sample_video, sample_video],
        output_path=str(tmp_path / "merged.mp4"),
        transitions=["dissolve"],
    )
    assert _pix_fmt(result.output_path) == "yuv420p"


def test_sepia_filter_emits_yuv420p(tmp_path, sample_video):
    result = apply_filter(input_path=sample_video, filter_type="sepia", output_path=str(tmp_path / "sepia.mp4"))
    assert _pix_fmt(result.output_path) == "yuv420p"


def test_layout_pip_renders_instead_of_raising(tmp_path):
    from mcp_video.effects_engine.layout import layout_pip

    main = str(tmp_path / "main.mp4")
    pip = str(tmp_path / "pip.mp4")
    _make_clip(main)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=160x120:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            pip,
        ],
        capture_output=True,
        timeout=60,
        check=True,
    )
    out = str(tmp_path / "pip_out.mp4")
    # Before the fix this raised ValueError (full ffprobe command passed to the
    # raw-args runner) before any rendering happened.
    result = layout_pip(main, pip, out, size=0.25)
    assert os.path.isfile(result)


def test_drawtext_family_resolves_to_concrete_file():
    option = _drawtext_font_option("Arial")
    assert "fontfile=" in option
    # The resolved path must exist and no longer be the fontconfig-only form.
    path = option.split("fontfile=", 1)[1].strip("'\"")
    assert os.path.isfile(path)


def test_drawtext_font_path_passthrough_unchanged():
    concrete = "/System/Library/Fonts/Helvetica.ttc"
    if not os.path.isfile(concrete):
        pytest.skip("macOS font not present")
    assert "fontfile=" in _drawtext_font_option(concrete)


def test_unresolvable_family_falls_back_to_legacy_option():
    resolved = _resolve_font_family_to_file("DefinitelyNotARealFontFamily12345")
    assert resolved is None
    option = _drawtext_font_option("DefinitelyNotARealFontFamily12345")
    assert option.startswith("font=")


def test_pil_font_loader_has_no_glob_name_error():
    # Regression for the silent NameError ('glob' is not defined) that pushed
    # every PIL text measurement onto the fallback path.
    try:
        _load_pil_font("NoSuchFamilyAtAll", 24)
    except Exception as exc:
        assert "glob" not in str(exc)


def test_pil_font_loader_finds_a_real_font():
    import platform

    pytest.importorskip("PIL")
    family = "Arial" if platform.system() in ("Darwin", "Windows") else "DejaVu Sans"
    font = _load_pil_font(family, 24)
    assert font is not None
