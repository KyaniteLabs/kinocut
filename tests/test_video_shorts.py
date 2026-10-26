"""Tests for the one-call shorts flow without invoking FFmpeg."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product import shorts_flow


def test_video_shorts_reuses_existing_engines_and_returns_one_receipt_chain(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    calls = []

    monkeypatch.setattr(shorts_flow, "_validate_input_path", lambda path: path)

    def fake_trim(input_path, *, start, end, output_path, accurate=True):
        calls.append(("trim", input_path, start, end))
        Path(output_path).write_bytes(b"trim")
        return SimpleNamespace(output_path=output_path)

    def fake_merge(clips, output_path=None, **_kwargs):
        calls.append(("merge", tuple(clips)))
        Path(output_path).write_bytes(b"merge")
        return SimpleNamespace(output_path=output_path)

    def fake_generate(entries, input_path, output_path, burn=False):
        calls.append(("caption-file", entries, input_path))
        Path(output_path).write_text("captions", encoding="utf-8")
        return SimpleNamespace(srt_path=output_path)

    def fake_subtitles(input_path, subtitle_path, output_path, style=None):
        calls.append(("caption", input_path, subtitle_path, style))
        Path(output_path).write_bytes(b"captioned")
        return SimpleNamespace(output_path=output_path)

    def fake_resize(input_path, *, aspect_ratio, output_path, quality):
        calls.append(("vertical", input_path, aspect_ratio, quality))
        Path(output_path).write_bytes(b"vertical")
        return SimpleNamespace(output_path=output_path)

    monkeypatch.setattr(shorts_flow, "trim", fake_trim)
    monkeypatch.setattr(shorts_flow, "merge", fake_merge)
    monkeypatch.setattr(shorts_flow, "generate_subtitles", fake_generate)
    monkeypatch.setattr(shorts_flow, "subtitles", fake_subtitles)
    monkeypatch.setattr(shorts_flow, "resize", fake_resize)

    result = shorts_flow.video_shorts(
        str(source),
        [
            {"start": 0, "end": 2, "text": "hello"},
            {"start": 3, "end": 5, "text": "world"},
        ],
        style={"caption_style": "FontSize=32"},
        output_path=str(tmp_path / "final.mp4"),
    )

    assert result["success"] is True
    assert result["output_path"].endswith("final.mp4")
    assert [call[0] for call in calls] == ["trim", "trim", "merge", "caption-file", "caption", "vertical"]
    assert result["receipt"]["receipt_kind"] == "video_shorts"
    assert len(result["receipt"]["steps"]) == 5
    assert result["external_posting"] is False


def test_video_shorts_rejects_bad_segment_range():
    with pytest.raises(MCPVideoError, match="end must be greater than start"):
        shorts_flow.video_shorts("source.mp4", [{"start": 2, "end": 1}])

