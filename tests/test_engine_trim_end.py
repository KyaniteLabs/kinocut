"""Trim-end absolute-timestamp semantics (contributor PR #493, WohaibHasan).

``end`` is an absolute source timestamp on the input-seeking path, not a
duration. Extracted from tests/test_engine.py to respect the 800-LOC module
ceiling; authorship preserved per the contributor policy.
"""

import pytest

from kinocut.engine_edit import trim
from kinocut.errors import MCPVideoError

from .test_engine import probe


class TestTrimEndSemantics:
    """``end`` is an absolute source timestamp, not a duration.

    ``sample_video`` is 3s. With ``start=1``, an absolute ``end=2`` yields a 1s
    clip, while treating ``end`` as a duration yields 2s -- so these cases
    distinguish the two readings without being clipped by the source length.
    The pre-existing ``test_trim_by_end`` uses ``start=0``, where both readings
    agree, which is why this regression went unnoticed.
    """

    def test_end_is_absolute_when_start_is_nonzero(self, sample_video, tmp_path):
        out = str(tmp_path / "by_end.mp4")
        trim(sample_video, start="1", end="2", output_path=out)
        assert abs(probe(out).duration - 1.0) < 0.25

    def test_end_matches_equivalent_duration(self, sample_video, tmp_path):
        by_end = str(tmp_path / "by_end.mp4")
        by_duration = str(tmp_path / "by_duration.mp4")
        trim(sample_video, start="1", end="2", output_path=by_end)
        trim(sample_video, start="1", duration="1", output_path=by_duration)
        assert abs(probe(by_end).duration - probe(by_duration).duration) < 0.25

    def test_end_is_absolute_in_accurate_mode(self, sample_video, tmp_path):
        out = str(tmp_path / "accurate.mp4")
        trim(sample_video, start="1", end="2", output_path=out, accurate=True)
        assert abs(probe(out).duration - 1.0) < 0.25

    def test_end_before_start_is_rejected(self, sample_video):
        with pytest.raises(MCPVideoError):
            trim(sample_video, start="2", end="1")


class TestTrimEndFFmpegArgs:
    """Argument-level contract for ``end``. Does not require FFmpeg."""

    @staticmethod
    def _capture_trim(monkeypatch, tmp_path, **kwargs):
        from kinocut import engine_edit

        source = tmp_path / "in.mp4"
        source.write_bytes(b"\x00")
        calls: list[list[str]] = []
        monkeypatch.setattr(engine_edit, "_run_ffmpeg", lambda cmd: calls.append(cmd))
        monkeypatch.setattr(engine_edit, "_build_edit_result", lambda *a, **k: None)
        engine_edit.trim(str(source), output_path=str(tmp_path / "out.mp4"), **kwargs)
        return calls[0]

    def test_input_seeking_converts_end_to_duration(self, monkeypatch, tmp_path):
        # -ss before -i rebases output timestamps to zero, so a trailing -to
        # would be measured from the seek point and act as a duration.
        cmd = self._capture_trim(monkeypatch, tmp_path, start="5", end="10")
        assert "-to" not in cmd
        assert "-t" in cmd
        assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(5.0)

    def test_output_seeking_keeps_end_absolute(self, monkeypatch, tmp_path):
        # -ss after -i preserves source timestamps, so -to is already absolute.
        cmd = self._capture_trim(monkeypatch, tmp_path, start="5", end="10", accurate=True)
        assert "-to" in cmd
        assert cmd[cmd.index("-to") + 1] == "10"

    def test_explicit_duration_is_passed_through(self, monkeypatch, tmp_path):
        cmd = self._capture_trim(monkeypatch, tmp_path, start="5", duration="10")
        assert cmd[cmd.index("-t") + 1] == "10"
        assert "-to" not in cmd

    def test_end_without_start_still_equals_end(self, monkeypatch, tmp_path):
        cmd = self._capture_trim(monkeypatch, tmp_path, end="10")
        assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(10.0)
