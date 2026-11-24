"""Production entrypoints, with only the speech recognizer and expensive audio decode stubbed."""

import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kinocut.ai_engine import ai_transcribe
from kinocut.ai_engine.transcribe import _format_json_transcript
from kinocut.engine_subtitles import subtitles
from kinocut.errors import MCPVideoError
from kinocut.product import IntakeReport, load_shorts_plan, measure_golden_render_ssim, propose_shorts_plan
from kinocut.product.models import (
    CandidateMoment,
    SelectionExample,
    SourceSignal,
    TranscriptSegment,
    canonical_dedup_key,
)
from kinocut.product.shorts_flow import video_shorts
from tests.subtitle_render_test_support import _AUTHORED_ASS


def _segment(*words, **extra):
    return {
        "start": words[0][1],
        "end": words[-1][2],
        "text": " ".join(word for word, _, _ in words),
        "words": [{"word": word, "start": start, "end": end} for word, start, end in words],
        **extra,
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
        segment = (
            _segment(("start.", 1490, 1491), tokens=[101, 102], compression_ratio=1.1, avg_logprob=-0.2)
            if starts[-1] == 0
            else _segment(("start", 5, 6), ("finish", 16, 17), tokens=[103, 104], compression_ratio=1.2)
        )
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
        assert result["transcript"] == "start. finish" and result["language"] == "en"
        assert [seg["id"] for seg in result["segments"]] == [0, 1]
        assert [(seg["start"], seg["end"], seg["text"]) for seg in result["segments"]] == [
            (1490, 1491, "start."),
            (1501, 1502, "finish"),
        ]
        assert result["segments"][0]["tokens"] == [101, 102]
        assert result["segments"][0]["compression_ratio"] == 1.1
        assert result["segments"][1]["tokens"] == [103, 104]
        assert result["segments"][1]["compression_ratio"] == 1.2
        sidecar = _format_json_transcript(result["transcript"], result["segments"], result["language"])
        assert [seg["tokens"] for seg in sidecar["segments"]] == [[101, 102], [103, 104]]
        assert [seg["compression_ratio"] for seg in sidecar["segments"]] == [1.1, 1.2]
        assert sidecar["segments"][1]["words"] == [{"word": "finish", "start": 1501.0, "end": 1502.0}]
        text = captions.read_text()
        assert text.count("start") == 1 and "00:25:01,000 --> 00:25:02,000" in text
        runs.append((text, result))
    assert runs[0] == runs[1] and starts == [0, 1485] * 3 and load.call_count == 3
    assert all(not path.parent.exists() for path in paths)


def test_longform_preserves_unaligned_speech_and_ignores_silent_chunk_language(tmp_path, monkeypatch):
    source = tmp_path / "long_mixed.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 1, 32, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x80" * (32 * 3100))
    starts = []

    def decode(cmd, **kwargs):
        starts.append(float(cmd[cmd.index("-ss") + 1]))

    def recognize(path, **options):
        offset = starts[-1]
        if offset == 0:
            return {
                "language": "en",
                "segments": [
                    _segment(("aligned", 1, 2), ("speech", 2, 3), tokens=[1, 2]),
                    {"start": 10, "end": 12, "text": "unaligned tail", "words": [], "tokens": [3, 4]},
                ],
            }
        return {"language": "nn", "segments": []}

    monkeypatch.setitem(
        sys.modules, "whisper", SimpleNamespace(load_model=lambda _: SimpleNamespace(transcribe=recognize))
    )
    monkeypatch.setattr("kinocut.ai_engine.transcribe._run_command", decode)
    result = ai_transcribe(str(source), model="tiny")
    assert result["language"] == "en"
    assert result["transcript"] == "aligned speech unaligned tail"
    assert [seg["text"] for seg in result["segments"]] == ["aligned speech", "unaligned tail"]


def test_longform_overlap_dedup_preserves_unicode_combining_marks(tmp_path, monkeypatch):
    source = tmp_path / "long_indic.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 1, 32, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x80" * (32 * 1801))
    starts = []

    def decode(cmd, **kwargs):
        starts.append(float(cmd[cmd.index("-ss") + 1]))

    def recognize(path, **options):
        if starts[-1] == 0:
            return {"language": "hi", "segments": [_segment(("मा", 1490, 1491))]}
        return {"language": "hi", "segments": [_segment(("माँ", 5.2, 6.2))]}

    monkeypatch.setitem(
        sys.modules, "whisper", SimpleNamespace(load_model=lambda _: SimpleNamespace(transcribe=recognize))
    )
    monkeypatch.setattr("kinocut.ai_engine.transcribe._run_command", decode)
    result = ai_transcribe(str(source), model="tiny", language="hi")
    assert result["transcript"] == "मा माँ"
    assert [seg["text"] for seg in result["segments"]] == ["मा", "माँ"]


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


@pytest.mark.parametrize("suffix", ["srt", "vtt", "ass"])
def test_subtitle_burn_warns_without_modifying_authored_input(tmp_path, sample_video, suffix):
    source = tmp_path / f"cues.{suffix}"
    text = "fast caption " * 18
    if suffix == "srt":
        content = f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n2\n00:00:00,500 --> 00:00:01,500\nShort.\n"
    elif suffix == "vtt":
        content = (
            "WEBVTT\n\n"
            f"00:00.000 --> 00:01.000 align:start position:10%\n{text}\n\n"
            "00:00.500\t-->\t00:01.500 align:end\nShort.\n"
        )
    else:
        content = _AUTHORED_ASS.replace("AUTHORED", text)
    source.write_text(content)
    result = subtitles(sample_video, str(source), str(tmp_path / "burn.mp4"), check_captions=True)
    assert result.success and Path(result.output_path).stat().st_size and source.read_text() == content
    assert any("reading_speed=1" in warning for warning in result.warnings)
    assert not any("unavailable" in warning for warning in result.warnings)
    if suffix in {"srt", "vtt"}:
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
    past_end = TranscriptSegment(segment_id="late_oob", start=45, end=60, text="Outside source duration.")
    with pytest.raises(MCPVideoError) as oob_transcript:
        propose_shorts_plan(
            job_id="shorts_0000000000000004",
            transcript=(past_end,),
            signals=(SourceSignal(kind="scene_change", timestamp=50, score=0.9),),
            **common,
        )
    assert oob_transcript.value.code == "shorts_out_of_range"
    with pytest.raises(MCPVideoError) as oob_signal:
        propose_shorts_plan(
            job_id="shorts_0000000000000005",
            transcript=(first,),
            signals=(SourceSignal(kind="scene_change", timestamp=50, score=0.9),),
            **common,
        )
    assert oob_signal.value.code == "shorts_out_of_range"
    oob_proposal = CandidateMoment(
        candidate_id="oob_01",
        start=35,
        end=45,
        transcript_excerpt="Outside fallback.",
        suggested_title="Too late",
        suggested_hook="Too late",
        rationale="Fallback",
        confidence=0.8,
        dedup_key=canonical_dedup_key(start=35, end=45, excerpt="Outside fallback.", sensitivity="none"),
    )
    with pytest.raises(MCPVideoError) as oob_fallback:
        propose_shorts_plan(
            job_id="shorts_0000000000000006",
            transcript=(),
            fallback_proposals=(oob_proposal,),
            **common,
        )
    assert oob_fallback.value.code == "shorts_out_of_range"
