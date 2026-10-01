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


def test_drawtext_family_resolves_to_concrete_file(monkeypatch):
    from kinocut.effects_engine import text as text_engine

    paths = []
    escape_path = text_engine._escape_ffmpeg_filter_path

    def capture_path(path):
        paths.append(path)
        return escape_path(path)

    monkeypatch.setattr(text_engine, "_escape_ffmpeg_filter_path", capture_path)
    option = _drawtext_font_option("Arial")
    # Check the actual resolver input, then the unchanged filter escaping.
    # A Windows drive colon in the filter literal is not a filesystem path.
    assert len(paths) == 1 and os.path.isfile(paths[0])
    assert option == f"fontfile={escape_path(paths[0])}"


def test_drawtext_font_path_passthrough_unchanged():
    concrete = "/System/Library/Fonts/Helvetica.ttc"
    if not os.path.isfile(concrete):
        pytest.skip("macOS font not present")
    assert "fontfile=" in _drawtext_font_option(concrete)


def test_unresolvable_family_falls_back_gracefully():
    import platform

    resolved = _resolve_font_family_to_file("DefinitelyNotARealFontFamily12345")
    if platform.system() == "Linux":
        # Deliberate resolver fallback: on fontconfig systems an unknown family
        # still resolves to a concrete file (DejaVu) rather than the
        # fontconfig-dependent font= option.
        assert resolved is not None and os.path.isfile(resolved)
        assert "fontfile=" in _drawtext_font_option("DefinitelyNotARealFontFamily12345")
    elif platform.system() == "Windows":
        from kinocut.errors import MCPVideoError

        assert resolved is None
        with pytest.raises(MCPVideoError) as failure:
            _drawtext_font_option("DefinitelyNotARealFontFamily12345")
        assert failure.value.code == "font_unavailable"
    else:
        # macOS/Windows resolve by directory listing: an unknown family has no
        # file, so the legacy family-name option is kept.
        assert resolved is None
        option = _drawtext_font_option("DefinitelyNotARealFontFamily12345")
        assert option.startswith("font=")


@pytest.mark.parametrize("explicit_font", [False, True])
def test_default_animated_text_renders_and_decodes(tmp_path, explicit_font):
    """Exercise #553 through Client and actual FFmpeg, including native CI."""
    from kinocut import Client

    source = str(tmp_path / "source.mp4")
    _make_clip(source, seconds="1")
    options = {}
    if explicit_font:
        concrete = _resolve_font_family_to_file("Arial")
        assert concrete and os.path.isfile(concrete)
        options["font"] = concrete
    result = Client().text_animated(
        source, "Hello", str(tmp_path / "animated.mp4"), animation="typewriter", duration=1.0, **options
    )
    assert _pix_fmt(result.output_path) == "yuv420p"
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", result.output_path, "-f", "null", "-"],
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert decoded.stderr == b""


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
