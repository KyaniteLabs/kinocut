"""Tests for visual effects engine behavior."""

from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError, ProcessingError


def test_chromatic_aberration_falls_back_when_chromashift_missing(tmp_path, monkeypatch):
    from mcp_video import effects_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    calls = []

    def fake_run_ffmpeg(cmd):
        calls.append(cmd.copy())
        if len(calls) == 1:
            raise ProcessingError(" ".join(cmd), 1, "No such filter: 'chromashift'")
        Path(cmd[-1]).write_bytes(b"output")

    monkeypatch.setattr(effects_engine.core, "_run_command", fake_run_ffmpeg)

    result = effects_engine.effect_chromatic_aberration(str(input_path), str(output_path), intensity=3.0)

    assert result == str(output_path)
    assert len(calls) == 2
    assert calls[0][5].startswith("chromashift=")
    assert calls[1][5].startswith("colorbalance=")


def test_glow_falls_back_when_gblur_missing(tmp_path, monkeypatch):
    from mcp_video import effects_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    calls = []

    def fake_run_ffmpeg(cmd):
        calls.append(cmd.copy())
        if len(calls) == 1:
            raise ProcessingError(" ".join(cmd), 1, "No such filter: 'gblur'")
        Path(cmd[-1]).write_bytes(b"output")

    monkeypatch.setattr(effects_engine.core, "_run_command", fake_run_ffmpeg)

    result = effects_engine.effect_glow(str(input_path), str(output_path), radius=15)

    assert result == str(output_path)
    assert len(calls) == 2
    assert "gblur=sigma=15" in calls[0][5]
    assert "boxblur=15:15" in calls[1][5]


def test_glow_uses_non_additive_blend_by_default(tmp_path, monkeypatch):
    from mcp_video import effects_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    calls = []

    def fake_run_ffmpeg(cmd):
        calls.append(cmd.copy())
        Path(cmd[-1]).write_bytes(b"output")

    monkeypatch.setattr(effects_engine.core, "_run_command", fake_run_ffmpeg)

    result = effects_engine.effect_glow(str(input_path), str(output_path), intensity=0.5)

    assert result == str(output_path)
    assert len(calls) == 1
    filter_graph = calls[0][5]
    assert "all_mode='addition'" not in filter_graph
    assert "all_mode='screen'" in filter_graph
    assert "all_opacity=0.25" in filter_graph


def test_film_noise_uses_luma_only_noise_filter(tmp_path, monkeypatch):
    from mcp_video import effects_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    calls = []

    def fake_run_ffmpeg(cmd):
        calls.append(cmd.copy())
        Path(cmd[-1]).write_bytes(b"output")

    monkeypatch.setattr(effects_engine.core, "_run_command", fake_run_ffmpeg)

    result = effects_engine.effect_noise(str(input_path), str(output_path), intensity=0.03, mode="film")

    assert result == str(output_path)
    assert len(calls) == 1
    filter_graph = calls[0][5]
    assert "geq=" not in filter_graph
    assert "noise=c0s=3.0" in filter_graph
    assert "c1s" not in filter_graph
    assert "c2s" not in filter_graph


def test_subtitle_text_is_wrapped_for_safe_area():
    from mcp_video.effects_engine.text import _wrap_subtitle_payload_for_safe_area

    source = "1\n00:00:00,000 --> 00:00:05,000\nThe same source becomes YouTube, Shorts, and square social cuts.\n"

    wrapped = _wrap_subtitle_payload_for_safe_area(source, max_chars_per_line=28)

    assert "The same source becomes\nYouTube, Shorts, and square\nsocial cuts." in wrapped


def test_mograph_count_rejects_invalid_duration_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import mograph_count
    from mcp_video.effects_engine import mograph as mograph_engine

    output = tmp_path / "count.mp4"
    monkeypatch.setattr(mograph_engine, "_run_command", lambda cmd: output.write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="duration"):
        mograph_count(0, 10, 0, str(output))

    assert not output.exists()


def test_mograph_progress_rejects_unknown_style_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import mograph as mograph_engine
    from mcp_video.effects_engine import mograph_progress

    output = tmp_path / "progress.mp4"
    monkeypatch.setattr(mograph_engine, "_run_command", lambda cmd: output.write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="style"):
        mograph_progress(1.0, str(output), style="spiral")

    assert not output.exists()


def test_layout_grid_rejects_unknown_layout_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import layout_grid
    from mcp_video.effects_engine import layout as layout_engine

    clip = tmp_path / "clip.mp4"
    output = tmp_path / "out.mp4"
    clip.write_bytes(b"placeholder")
    monkeypatch.setattr(layout_engine, "_run_command", lambda cmd: output.write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="layout"):
        layout_grid([str(clip)], "9x9", str(output))

    assert not output.exists()


def test_layout_pip_rejects_unknown_position_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import layout_pip
    from mcp_video.effects_engine import layout as layout_engine

    main = tmp_path / "main.mp4"
    pip = tmp_path / "pip.mp4"
    output = tmp_path / "out.mp4"
    main.write_bytes(b"placeholder")
    pip.write_bytes(b"placeholder")
    monkeypatch.setattr(layout_engine, "_run_ffmpeg", lambda cmd: type("Probe", (), {"stdout": "1920x1080"})())
    monkeypatch.setattr(layout_engine, "_run_command", lambda cmd: output.write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="position"):
        layout_pip(str(main), str(pip), str(output), position="middle")

    assert not output.exists()


def test_text_animated_rejects_empty_text_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import text_animated
    from mcp_video.effects_engine import text as text_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    monkeypatch.setattr(text_engine, "_run_command", lambda cmd: Path(cmd[-1]).write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="Text cannot be empty"):
        text_animated(str(input_path), "   ", str(output_path))

    assert not output_path.exists()


def test_text_animated_rejects_unknown_animation_before_ffmpeg(tmp_path, monkeypatch):
    from mcp_video.effects_engine import text_animated
    from mcp_video.effects_engine import text as text_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    monkeypatch.setattr(text_engine, "_run_command", lambda cmd: Path(cmd[-1]).write_bytes(b"output"))

    with pytest.raises(MCPVideoError, match="animation"):
        text_animated(str(input_path), "Hello", str(output_path), animation="spin")

    assert not output_path.exists()


def test_webvtt_metadata_blocks_are_preserved_during_safe_area_wrap():
    from mcp_video.effects_engine.text import _wrap_subtitle_payload_for_safe_area

    source = (
        "WEBVTT\n\n"
        "STYLE\n"
        "::cue { color: lime; }\n\n"
        "NOTE generated by editorial system\n\n"
        "REGION\n"
        "id:bottom\n"
        "lines:3\n\n"
        "00:00:00.000 --> 00:00:05.000\n"
        "This caption line is deliberately long enough that it should wrap safely.\n"
    )

    wrapped = _wrap_subtitle_payload_for_safe_area(source, max_chars_per_line=24)

    assert "STYLE\n::cue { color: lime; }" in wrapped
    assert "NOTE generated by editorial system" in wrapped
    assert "REGION\nid:bottom\nlines:3" in wrapped
    assert "This caption line is\ndeliberately long enough\nthat it should wrap…" in wrapped


def test_chromatic_aberration_reraises_unrelated_processing_error(tmp_path, monkeypatch):
    from mcp_video import effects_engine

    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"placeholder")
    error = ProcessingError("ffmpeg", 1, "encoder failed")

    def fake_run_ffmpeg(cmd):
        raise error

    monkeypatch.setattr(effects_engine.core, "_run_command", fake_run_ffmpeg)

    try:
        effects_engine.effect_chromatic_aberration(str(input_path), str(output_path))
    except ProcessingError as exc:
        assert exc is error
    else:
        raise AssertionError("Expected ProcessingError")
