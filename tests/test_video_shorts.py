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

    def fake_probe(_path):
        # The flow bounds segment ranges by the measured source duration
        # (t_e3775201 F7); this fixture is a placeholder file, so the probe
        # is stubbed rather than run against a non-media file.
        return SimpleNamespace(duration=10.0)

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
    monkeypatch.setattr("kinocut.engine_probe.probe", fake_probe)

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


def test_video_shorts_rerun_with_overwrite_replaces_prior_output(sample_video, tmp_path):
    """Real guards (t_e3775201 F6): a captioned re-run must be possible with
    overwrite consent — no stale companion sidecar may block the flow."""
    import os
    from pathlib import Path

    output = str(tmp_path / "short.mp4")
    segments = [{"start": 0.0, "end": 1.5, "text": "one"}]

    first = shorts_flow.video_shorts(sample_video, segments, output_path=output)
    assert first["success"] is True
    assert os.path.isfile(output)
    # The burn-in SRT is a transient build input in the flow-owned workdir,
    # never a durable companion next to the requested output.
    assert not os.path.exists(str(Path(output).with_suffix(".srt")))

    with pytest.raises(MCPVideoError) as refusal:
        shorts_flow.video_shorts(sample_video, segments, output_path=output)
    # The retry invocation is part of the serialized error payload, not the
    # raised message; the refusal must still name the overwrite consent.
    assert "overwrite=true" in refusal.value.to_dict()["message"]

    second = shorts_flow.video_shorts(sample_video, segments, output_path=output, overwrite=True)
    assert second["success"] is True
    assert os.path.isfile(output)


def test_video_shorts_refuses_segment_past_source_eof_before_rendering(sample_video, tmp_path):
    """Source-bounded ranges (t_e3775201 F7): a segment beyond EOF is refused
    up front, so caption timing can never silently disagree with the media."""
    import os

    output = str(tmp_path / "short.mp4")
    with pytest.raises(MCPVideoError, match="exceeds the source duration"):
        shorts_flow.video_shorts(
            sample_video,
            [{"start": 0.0, "end": 999.0, "text": "x"}],
            output_path=output,
        )
    assert not os.path.exists(output), "refusal must arrive before any rendering"


def test_video_shorts_receipt_carries_caption_warnings(sample_video, tmp_path):
    """Receipt honesty (t_e3775201 F7): caption-stage warnings and any rendered
    entry-count divergence propagate into the receipt."""
    result = shorts_flow.video_shorts(
        sample_video,
        [{"start": 0.0, "end": 1.5, "text": "hello"}],
        output_path=str(tmp_path / "short.mp4"),
    )
    steps = {step["stage"]: step for step in result["receipt"]["steps"]}
    assert "warnings" in steps["captions"]


def test_video_shorts_refuses_to_overwrite_its_own_input(tmp_path, monkeypatch):
    """Gate 2 P2-1: the direct product-function path must never publish over
    the operation's own input, even with explicit overwrite consent.

    A fresh ``output_operation`` scope resets the recorded-input set, so
    validating the source before opening the scope let the source be
    forgotten and the publish target it. The engines are stubbed so that a
    regression is caught by the bytes, not by a missing FFmpeg binary.
    """
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original bytes")

    def fake_probe(_path):
        return SimpleNamespace(duration=10.0)

    def fake_trim(input_path, *, start, end, output_path, accurate=True):
        Path(output_path).write_bytes(b"trim")
        return SimpleNamespace(output_path=output_path)

    def fake_merge(clips, output_path=None, **_kwargs):
        Path(output_path).write_bytes(b"merge")
        return SimpleNamespace(output_path=output_path)

    def fake_generate(entries, input_path, output_path, burn=False):
        Path(output_path).write_text("captions", encoding="utf-8")
        return SimpleNamespace(srt_path=output_path)

    def fake_subtitles(input_path, subtitle_path, output_path, style=None):
        Path(output_path).write_bytes(b"captioned")
        return SimpleNamespace(output_path=output_path)

    def fake_resize(input_path, *, aspect_ratio, output_path, quality):
        Path(output_path).write_bytes(b"vertical")
        return SimpleNamespace(output_path=output_path)

    monkeypatch.setattr(shorts_flow, "trim", fake_trim)
    monkeypatch.setattr(shorts_flow, "merge", fake_merge)
    monkeypatch.setattr(shorts_flow, "generate_subtitles", fake_generate)
    monkeypatch.setattr(shorts_flow, "subtitles", fake_subtitles)
    monkeypatch.setattr(shorts_flow, "resize", fake_resize)
    monkeypatch.setattr("kinocut.engine_probe.probe", fake_probe)

    with pytest.raises(MCPVideoError) as refusal:
        shorts_flow.video_shorts(
            str(source),
            [{"start": 0.0, "end": 2.0, "text": "hello"}],
            output_path=str(source),
            overwrite=True,
        )

    assert refusal.value.code == "invalid_output_path"
    assert source.read_bytes() == b"original bytes"
