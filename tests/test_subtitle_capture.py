"""Prove diagnostic apparatus retains distinct conversion and burn failures."""

import json
from pathlib import Path
import subprocess

import pytest

from kinocut.errors import MCPVideoError
from tests.subtitle_capture import SubtitleCapture


def test_header_only_conversion_is_retained_and_rejected_before_burn(tmp_path, monkeypatch):
    from kinocut import subtitles_common

    def conversion(args, **kwargs):
        Path(args[-1]).write_text("[Script Info]\n")
        return subprocess.CompletedProcess(args, 0, "", "zero-exit conversion")

    monkeypatch.setattr(subtitles_common, "_run_ffmpeg", conversion)
    monkeypatch.setattr(subtitles_common, "_require_filter", lambda *_: None)
    capture = SubtitleCapture(tmp_path, monkeypatch)
    subtitle = tmp_path / "a.vtt"
    subtitle.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n")
    with (
        pytest.raises(MCPVideoError) as excinfo,
        subtitles_common.staged_burn_source(
            str(subtitle), "unused", str(tmp_path / "out.mp4"), display_size=(320, 480)
        ),
    ):
        pytest.fail("header-only conversion reached burn")
    assert excinfo.value.code == "subtitle_no_cues"
    evidence = json.loads((capture.root / "capture.json").read_text())
    assert evidence["stages"]["conversion"]["returncode"] == 0
    assert evidence["stages"]["conversion"]["dialogue_count"] == 0
    assert "staged" not in evidence["stages"]
    assert (capture.root / "conversion.ass").read_text() == "[Script Info]\n"
    assert list(tmp_path.glob("*.ass")) == []


def test_zero_exit_burn_with_missing_pixels_keeps_correct_ass(tmp_path, monkeypatch):
    from kinocut import engine_subtitles, subtitles_common

    monkeypatch.setattr(
        engine_subtitles, "_run_ffmpeg", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "burn claims SUCCESS")
    )
    monkeypatch.setattr(subtitles_common, "_require_filter", lambda *_: None)
    capture = SubtitleCapture(tmp_path, monkeypatch)
    authored = tmp_path / "original.ass"
    authored.write_text("[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello\n")
    with subtitles_common.staged_burn_source(str(authored), "unused", str(tmp_path / "out.mp4")) as staged:
        assert Path(staged.path).read_bytes() == authored.read_bytes()
        engine_subtitles._run_ffmpeg(["simulated-burn"])
    assert not Path(staged.path).exists()
    source, output = tmp_path / "source", tmp_path / "output"
    source.write_bytes(b"identical black pixels")
    output.write_bytes(source.read_bytes())
    capture.pixels(source, output, (320, 480), 0, 0)
    evidence = json.loads((capture.root / "capture.json").read_text())
    assert evidence["stages"]["staged"]["dialogue_count"] == 1
    assert evidence["stages"]["burn"]["returncode"] == 0
    assert evidence["caption_region_peak"] == 0
    assert evidence["source_sha256"] == evidence["output_sha256"]
