"""Production entrypoints, with only the speech recognizer and expensive audio decode stubbed."""

import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kinocut.ai_engine import ai_transcribe
from kinocut.engine_subtitles import subtitles
from kinocut.errors import MCPVideoError
from kinocut.product import IntakeReport, load_shorts_plan, measure_golden_render_ssim, propose_shorts_plan
from kinocut.product.models import SelectionExample, SourceSignal, TranscriptSegment
from kinocut.product.shorts_flow import video_shorts
from tests.subtitle_render_test_support import _AUTHORED_ASS


def _segment(*words):
    return {
        "start": words[0][1],
        "end": words[-1][2],
        "text": " ".join(word for word, _, _ in words),
        "words": [{"word": word, "start": start, "end": end} for word, start, end in words],
    }


def test_auto_longform_retries_cleanly_and_deduplicates_srt(tmp_path, monkeypatch):
    source = tmp_path / "long.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 1, 32, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x80" * (32 * 1801))
    paths = []
    starts = []

    def decode(cmd, **kwargs):
        starts.append(float(cmd[cmd.index("-ss") + 1]))
        paths.append(Path(cmd[-1]))
        assert paths[-1].exists()

    def recognize(path, **options):
        assert Path(path) == paths[-1]
        assert options == {"task": "transcribe", "word_timestamps": True, "language": "en"}
        if len(paths) == 2:
            raise RuntimeError("backend stopped")
        segment = _segment(("start", 1490, 1491)) if starts[-1] == 0 else _segment(("start", 5, 6), ("finish", 16, 17))
        return {"segments": [segment], "language": "en"}

    load = Mock(return_value=SimpleNamespace(transcribe=recognize))
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=load))
    monkeypatch.setattr("kinocut.ai_engine.transcribe._run_command", decode)
    failed = tmp_path / "failed.srt"
    with pytest.raises(RuntimeError, match="backend stopped"):
        ai_transcribe(str(source), str(failed), "tiny", "en")
    assert not failed.exists() and all(not path.parent.exists() for path in paths)
    runs = []
    for name in ("retry.srt", "repeat.srt"):
        captions = tmp_path / name
        result = ai_transcribe(str(source), str(captions), "tiny", "en")
        assert set(result) == {"transcript", "language", "segments"}
        assert result["transcript"] == "start finish" and result["language"] == "en"
        assert result["segments"] == [
            {"id": 0, "start": 1490, "end": 1491, "text": "start"},
            {"id": 1, "start": 1501, "end": 1502, "text": "finish"},
        ]
        text = captions.read_text()
        assert text.count("start") == 1 and "00:25:01,000 --> 00:25:02,000" in text
        runs.append((text, result))
    assert runs[0] == runs[1] and starts == [0, 1485] * 3 and load.call_count == 3
    assert all(not path.parent.exists() for path in paths)


@pytest.mark.parametrize(("duration", "chunk", "chunked"), [(1800, None, False), (1801, False, False), (3, True, True)])
def test_single_pass_and_chunk_overrides(sample_video, monkeypatch, duration, chunk, chunked):
    model = Mock()
    model.transcribe.return_value = {"text": "hello", "segments": [_segment(("hello", 0, 1))], "language": "en"}
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=lambda _: model))
    monkeypatch.setattr("kinocut.ai_engine.transcribe._get_video_duration", lambda _: duration)
    result = ai_transcribe(sample_video, chunk_longform=chunk)
    assert result["transcript"] == "hello"
    assert model.transcribe.call_args.kwargs.get("word_timestamps", False) is chunked
    assert not Path(model.transcribe.call_args.args[0]).exists()


@pytest.mark.parametrize("suffix", ["srt", "ass"])
def test_subtitle_burn_warns_without_modifying_authored_input(tmp_path, sample_video, suffix):
    source = tmp_path / f"cues.{suffix}"
    text = "fast caption " * 18
    content = (
        f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n2\n00:00:00,500 --> 00:00:01,500\nShort.\n"
        if suffix == "srt"
        else _AUTHORED_ASS.replace("AUTHORED", text)
    )
    source.write_text(content)
    result = subtitles(sample_video, str(source), str(tmp_path / "burn.mp4"), check_captions=True)
    assert result.success and Path(result.output_path).stat().st_size and source.read_text() == content
    assert any("reading_speed=1" in warning for warning in result.warnings)
    if suffix == "srt":
        assert any("overlap=1" in warning for warning in result.warnings)


@pytest.mark.parametrize(("text", "passed"), [("Hi", True), ("0123456789" * 15, False)])
def test_vertical_shorts_qa_measures_generated_captions(tmp_path, sample_video, text, passed):
    result = video_shorts(sample_video, [(0, 1, text)], output_path=str(tmp_path / "short.mp4"))
    stage = next(step for step in result["receipt"]["steps"] if step["stage"] == "captions")
    summary = stage["subtitle_qa"]
    assert summary["profile"] == "vertical" and summary["passed"] is passed
    assert summary["cue_count"] == 1 and summary["overlap_count"] == 0
    assert summary["max_cps"] == pytest.approx(len(text), rel=0.15)
    assert summary["safe_area_violations"] == summary["findings"].get("safe_area", 0)
    assert summary["findings"].get("reading_speed", 0) == int(not passed)


def test_new_plan_ranks_evidence_before_saving_and_never_reranks_on_load(tmp_path, sample_video):
    intake = IntakeReport(
        source_path="source.mp4", source_sha256="1" * 64, duration=40, width=640, height=360, audio_available=True
    )
    first = TranscriptSegment(segment_id="early", start=0, end=15, text="First complete thought.")
    last = TranscriptSegment(segment_id="late", start=20, end=35, text="Other complete thought.")
    common = dict(
        project_dir=str(tmp_path), output_dir=str(tmp_path / "plans"), intake=intake, platforms=("youtube-shorts",)
    )
    example = SelectionExample(example_id="approved", transcript_excerpt=last.text)
    signals = (
        SourceSignal(kind="audio_energy", timestamp=22, score=1),
        SourceSignal(kind="scene_change", timestamp=22, score=0.8),
    )
    plan = propose_shorts_plan(
        job_id="shorts_0000000000000001", transcript=(first, last), signals=signals, examples=(example,), **common
    )
    pick = plan.proposals[0]
    assert pick.start == last.start and pick.source_signals == signals and pick.selection_example_ids == ("approved",)
    assert load_shorts_plan(common["output_dir"]) == plan and not plan.decisions
    compare = measure_golden_render_ssim(
        sample_video,
        sample_video,
        selection_record_id=pick.candidate_id,
        selection_example_ids=pick.selection_example_ids,
    )
    assert compare.passed and compare.ssim == 1 and compare.byte_identical
    fallback = propose_shorts_plan(
        job_id="shorts_0000000000000002", transcript=(), fallback_proposals=(pick,), **common
    )
    assert fallback.proposals == (pick,) and not fallback.decisions
    with pytest.raises(MCPVideoError) as exc:
        propose_shorts_plan(job_id="shorts_0000000000000003", transcript=(), **common)
    assert exc.value.code == "shorts_no_candidates"
