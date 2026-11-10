"""The Shorts flow asks for what it can evidence, and asks for no more.

Two rules live here. A render with no caption text never reads a timing, so
an unmeasurable segment must not block it. And a receipt that carries a
bounded list says so when it leaves entries out.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kinocut.product import shorts_flow


def _stub_engines(monkeypatch, tmp_path) -> None:
    """Trim, merge and resize without touching a media file."""

    def fake_trim(input_path, *, start, end, output_path, accurate=True):
        Path(output_path).write_bytes(b"trim")
        return SimpleNamespace(output_path=output_path)

    def fake_merge(clips, output_path, **_kwargs):
        Path(output_path).write_bytes(b"merge")
        return SimpleNamespace(output_path=output_path)

    def fake_resize(input_path, *, aspect_ratio, output_path, quality):
        Path(output_path).write_bytes(b"vertical")
        return SimpleNamespace(output_path=output_path)

    monkeypatch.setattr(shorts_flow, "trim", fake_trim)
    monkeypatch.setattr(shorts_flow, "merge", fake_merge)
    monkeypatch.setattr(shorts_flow, "resize", fake_resize)
    monkeypatch.setattr("kinocut.engine_probe.probe", lambda path: SimpleNamespace(duration=60.0))


def test_a_captionless_render_does_not_need_a_measured_timeline(tmp_path, monkeypatch):
    # A flow with no caption text never reads a timing, so a segment that
    # cannot be measured must not block the render.
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(shorts_flow, "_validate_input_path", lambda path: path)
    _stub_engines(monkeypatch, tmp_path)

    def no_measurement(paths):
        raise AssertionError("a captionless flow must not measure a timeline")

    monkeypatch.setattr(shorts_flow, "_measured_segment_durations", no_measurement)

    result = shorts_flow.video_shorts(
        str(source),
        [{"start": 0, "end": 2, "text": None}, {"start": 0, "end": 5, "text": None}],
        output_path=str(tmp_path / "final.mp4"),
    )
    steps = {step["stage"]: step for step in result["receipt"]["steps"]}
    assert steps["captions"]["status"] == "skipped"
    assert steps["captions"]["reason"] == "segments have no text"


def test_a_captionless_render_does_not_need_the_source_measured(tmp_path, monkeypatch):
    # A flow with no caption text never reads a timing, so it has no reason
    # to measure the source either. An unmeasurable source must not fail it.
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(shorts_flow, "_validate_input_path", lambda path: path)
    _stub_engines(monkeypatch, tmp_path)

    def no_probe(path):
        raise AssertionError("a captionless flow must not measure the source")

    monkeypatch.setattr("kinocut.engine_probe.probe", no_probe)

    result = shorts_flow.video_shorts(
        str(source),
        [{"start": 0, "end": 2, "text": None}],
        output_path=str(tmp_path / "final.mp4"),
    )
    steps = {step["stage"]: step for step in result["receipt"]["steps"]}
    assert steps["captions"]["status"] == "skipped"


def test_a_bounded_request_list_says_it_was_truncated():
    # The receipt lists at most 50 requested entries. When it leaves some
    # out, it says how many — a partial list presented as complete is a lie.
    entries = [{"start": float(index), "end": float(index) + 1, "text": f"c{index}"} for index in range(51)]
    generated = SimpleNamespace(entries=tuple(entries), entry_count=51, warnings=())
    step = shorts_flow._caption_receipt(entries, generated, 0)
    assert step["requested_entry_count"] == 51
    assert len(step["requested_entries"]) == 50
    assert step["requested_entries_truncated"] == 1
    assert any("not listed in this receipt" in warning for warning in step["warnings"])
