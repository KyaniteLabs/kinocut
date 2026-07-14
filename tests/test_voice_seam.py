"""Voice-seam metrics and aggregate report coverage (Wave 4.2 PR 4.2).

``analyze_voice_seam`` clamps ASR segments to the real EOF *before* any derived
metric, reusing the canonical :func:`clamp_segments_to_eof`. Deterministic
style metrics (pace, cadence, silence/loudness seams) compute without ML;
optional speaker-identity providers are capability-gated and fail soft. The
composed :class:`AudioSeamReport` carries no raw transcript, PII, or host
paths — only bounded codes, hashes, counts, and unit-carrying measurements.

Every test is prefixed ``test_voice_seam_`` so a focused ``-k voice_seam`` gate
runs the entire contract.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from typing import Any

import pytest

from kinocut.aivideo.voice_seam import (
    AudioSeamReport,
    LoudnessSummary,
    SpeakerIdentityAvailability,
    SpeakerIdentityProvider,
    SpeakerIdentityResult,
    TranscriptTimingSummary,
    VoiceSeamFinding,
    VoiceSeamFindingCode,
    VoiceSeamMetric,
    VoiceSeamSeverity,
    VoiceStyleReport,
    analyze_voice_seam,
)
from kinocut.errors import MCPVideoError


# --------------------------------------------------------------------------- #
# Audio fixtures
# --------------------------------------------------------------------------- #


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run_ffmpeg(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def speech_audio(tmp_path_factory) -> str:
    """A 6-second 440Hz mono WAV representing a continuous voice-like bed."""
    if not _has_ffmpeg():
        pytest.skip("FFmpeg not installed")
    path = str(tmp_path_factory.mktemp("voice") / "speech.wav")
    _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-ac", "1", "-ar", "16000", path])
    return path


@pytest.fixture
def quiet_audio(tmp_path_factory) -> str:
    """A 6-second very quiet tone that should trip the lower LUFS bound."""
    if not _has_ffmpeg():
        pytest.skip("FFmpeg not installed")
    path = str(tmp_path_factory.mktemp("voice") / "quiet.wav")
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-af",
            "volume=0.005",
            "-ac",
            "1",
            "-ar",
            "16000",
            path,
        ]
    )
    return path


@pytest.fixture
def loud_audio(tmp_path_factory) -> str:
    """A 6-second loud tone that stays within the LUFS bounds."""
    if not _has_ffmpeg():
        pytest.skip("FFmpeg not installed")
    path = str(tmp_path_factory.mktemp("voice") / "loud.wav")
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-af",
            "volume=2.0",
            "-ac",
            "1",
            "-ar",
            "16000",
            path,
        ]
    )
    return path


# --------------------------------------------------------------------------- #
# Deterministic ASR-shaped inputs
# --------------------------------------------------------------------------- #


def _phrase(i: int, start: float, end: float, text: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"start": start, "end": end, "id": i}
    if text is not None:
        record["text"] = text
    return record


# --------------------------------------------------------------------------- #
# Test providers
# --------------------------------------------------------------------------- #


class _MatchingSpeaker(SpeakerIdentityProvider):
    provider_id = "test.speaker.match"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        return SpeakerIdentityResult(
            provider_id=self.provider_id,
            availability=SpeakerIdentityAvailability.IDENTIFIED,
            similarity_score=0.92,
            reference_label="reference_profile_a",
        )


class _MismatchSpeaker(SpeakerIdentityProvider):
    """Returns 0.519 similarity — the canonical '0.519-like' mismatch case."""

    provider_id = "test.speaker.mismatch"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        return SpeakerIdentityResult(
            provider_id=self.provider_id,
            availability=SpeakerIdentityAvailability.IDENTIFIED,
            similarity_score=0.519,
            reference_label="reference_profile_a",
        )


class _SixtyPctSpeaker(SpeakerIdentityProvider):
    provider_id = "test.speaker.sixty"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        return SpeakerIdentityResult(
            provider_id=self.provider_id,
            availability=SpeakerIdentityAvailability.IDENTIFIED,
            similarity_score=0.6,
            reference_label="reference_profile_a",
        )


class _FailingSpeaker(SpeakerIdentityProvider):
    provider_id = "test.speaker.failing"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        raise RuntimeError("speaker model could not load")


class _HostileIdFailingSpeaker(SpeakerIdentityProvider):
    provider_id = "/private/provider/path"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        raise RuntimeError("speaker model could not load")


class _RaisingIdSpeaker(SpeakerIdentityProvider):
    @property
    def provider_id(self) -> str:
        raise RuntimeError("provider metadata unavailable")

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        raise RuntimeError("speaker model could not load")


class _ConstructedHostileResultSpeaker(SpeakerIdentityProvider):
    provider_id = "test.speaker.hostile_result"

    def identify(self, audio_path: str) -> SpeakerIdentityResult:
        return SpeakerIdentityResult.model_construct(
            provider_id="/private/provider/path",
            availability=SpeakerIdentityAvailability.PROVIDER_FAILED,
            reason_code="provider_raised_exception",
        )


# --------------------------------------------------------------------------- #
# 1. EOF clamp before metrics
# --------------------------------------------------------------------------- #


def test_voice_seam_eof_overflow_is_clamped_before_metrics(speech_audio):
    """An ASR segment overshooting EOF is clamped, not silently dropped."""
    segments = [_phrase(0, 0.0, 3.0, "hello world"), _phrase(1, 3.0, 999.0, "overflow tail")]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    assert report.transcript_timing.segments_clamped == 1
    assert report.transcript_timing.segments_dropped == 0
    assert report.transcript_timing.segment_count == 2


def test_voice_seam_eof_pair_starting_at_eof_is_dropped(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "first"), _phrase(1, 6.0, 9.0, "post-eof")],
        6.0,
    )
    assert report.transcript_timing.segments_dropped == 1
    assert report.transcript_timing.segment_count == 1


def test_voice_seam_eof_negative_start_is_rejected_with_stable_error(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(speech_audio, [_phrase(0, -1.0, 2.0, "negative")], 6.0)
    assert excinfo.value.code == "invalid_eof_clamp"
    assert "-1" not in str(excinfo.value)


def test_voice_seam_eof_nonmonotonic_is_rejected_with_stable_error(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(
            speech_audio,
            [_phrase(0, 0.0, 4.0, "first"), _phrase(1, 2.0, 5.0, "overlap")],
            6.0,
        )
    assert excinfo.value.code == "invalid_eof_clamp"


def test_voice_seam_eof_nonfinite_time_is_rejected(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(speech_audio, [_phrase(0, math.inf, 2.0, "inf")], 6.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_voice_seam_eof_zero_eof_is_rejected(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 1.0, "first")], 0.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_voice_seam_eof_bad_container_is_rejected(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(speech_audio, "not-a-list", 6.0)  # type: ignore[arg-type]
    assert excinfo.value.code == "invalid_eof_clamp"


def test_voice_seam_eof_bad_segment_is_rejected(speech_audio):
    with pytest.raises(MCPVideoError) as excinfo:
        analyze_voice_seam(speech_audio, [("only", "one-field")], 6.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_voice_seam_eof_malformed_does_not_produce_partial_report(speech_audio):
    """No AudioSeamReport is returned when the input is malformed — fail closed."""
    with pytest.raises(MCPVideoError):
        analyze_voice_seam(speech_audio, [_phrase(0, 5.0, 2.0, "inverted")], 6.0)


def test_voice_seam_empty_segments_records_transcript_empty_not_raise(speech_audio):
    """An empty ASR list is a valid (degenerate) input — record, do not crash."""
    report = analyze_voice_seam(speech_audio, [], 6.0)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.TRANSCRIPT_EMPTY in codes
    assert report.transcript_timing.segment_count == 0
    assert report.transcript_timing.total_speech_seconds == 0.0


def test_voice_seam_eof_pair_segments_are_accepted(speech_audio):
    """Bare (start, end) pair segments — no mapping fields — are supported."""
    report = analyze_voice_seam(speech_audio, [(0.0, 3.0), (3.0, 6.0)], 6.0)
    assert report.transcript_timing.segment_count == 2
    assert report.transcript_timing.segments_clamped == 0


# --------------------------------------------------------------------------- #
# 2. Voice-style check: deterministic metrics
# --------------------------------------------------------------------------- #


def test_voice_seam_pace_is_deterministic_from_asr_text(speech_audio):
    segments = [
        _phrase(0, 0.0, 3.0, "one two three four five six seven eight nine ten"),
        _phrase(1, 3.0, 6.0, "eleven twelve thirteen fourteen fifteen"),
    ]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    metric = {m.name: m.value for m in report.voice_style.metrics}
    # 15 words across 6 seconds of speech = 150 wpm
    assert metric["pace_words_per_minute"] == pytest.approx(150.0, abs=0.5)


def test_voice_seam_pace_outlier_produces_finding(speech_audio):
    """A wildly high word rate trips the pace_outlier bound."""
    text = " ".join(["word"] * 100)  # 100 words in 6s = 1000 wpm
    segments = [_phrase(0, 0.0, 6.0, text)]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.PACE_OUTLIER in codes


def test_voice_seam_cadence_metric_is_bounded(speech_audio):
    segments = [_phrase(i, i * 1.0, (i + 1) * 1.0, f"seg {i}") for i in range(6)]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    metric = {m.name: m.value for m in report.voice_style.metrics}
    assert metric["cadence_segments_per_minute"] == pytest.approx(60.0, abs=0.5)


def test_voice_seam_silence_seam_detected_when_gap_exceeds_threshold(speech_audio):
    """A 2s gap between two ASR segments within EOF is a silence seam."""
    segments = [_phrase(0, 0.0, 1.0, "first"), _phrase(1, 3.0, 4.0, "second")]
    report = analyze_voice_seam(speech_audio, segments, 6.0, silence_seam_seconds=1.5)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.SILENCE_SEAM in codes
    silence = next(f for f in report.findings if f.code is VoiceSeamFindingCode.SILENCE_SEAM)
    assert silence.time_range[0] >= 1.0
    assert silence.time_range[1] <= 3.0


def test_voice_seam_no_silence_seam_when_segments_are_contiguous(speech_audio):
    segments = [_phrase(0, 0.0, 2.0, "first"), _phrase(1, 2.0, 4.0, "second")]
    report = analyze_voice_seam(speech_audio, segments, 6.0, silence_seam_seconds=1.5)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.SILENCE_SEAM not in codes


def test_voice_seam_word_level_asr_no_false_silence_seam(speech_audio):
    """Word-level ASR has tiny per-word gaps — must not fabricate silence seams.

    A 'word-level false negative' check: contiguous words must NOT be reported
    as a silence seam, regardless of segment granularity.
    """
    words = ["the", "quick", "brown", "fox", "jumps"]
    segments = [_phrase(i, i * 0.3, (i + 1) * 0.3, w) for i, w in enumerate(words)]
    report = analyze_voice_seam(speech_audio, segments, 6.0, silence_seam_seconds=1.5)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.SILENCE_SEAM not in codes
    assert report.transcript_timing.segment_count == len(words)


def test_voice_seam_word_level_asr_pace_matches_aggregate(speech_audio):
    """Pace from word-level segments matches the aggregate (single segment)."""
    words = ["one", "two", "three", "four", "five"]
    word_segments = [_phrase(i, i * 0.4, (i + 1) * 0.4, w) for i, w in enumerate(words)]
    single_segment = [_phrase(0, 0.0, 2.0, " ".join(words))]
    report_words = analyze_voice_seam(speech_audio, word_segments, 6.0)
    report_single = analyze_voice_seam(speech_audio, single_segment, 6.0)
    pace_words = {m.name: m.value for m in report_words.voice_style.metrics}["pace_words_per_minute"]
    pace_single = {m.name: m.value for m in report_single.voice_style.metrics}["pace_words_per_minute"]
    assert pace_words == pytest.approx(pace_single, rel=0.01)


def test_voice_seam_no_text_segments_skip_pace_but_keep_cadence(speech_audio):
    """Pair segments without text yield cadence but no words-per-minute."""
    report = analyze_voice_seam(speech_audio, [(0.0, 3.0), (3.0, 6.0)], 6.0)
    names = {m.name for m in report.voice_style.metrics}
    assert "cadence_segments_per_minute" in names
    assert "pace_words_per_minute" not in names


# --------------------------------------------------------------------------- #
# 3. Loudness seam (real audio)
# --------------------------------------------------------------------------- #


def test_voice_seam_loudness_summary_runs_on_real_audio(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 5.0, "hello")], 6.0)
    assert report.loudness.analysis_available is True
    assert report.loudness.integrated_lufs is not None
    assert isinstance(report.loudness.integrated_lufs, float)


def test_voice_seam_loudness_seam_flagged_when_far_below_bound(quiet_audio):
    """A near-silent asset falls below the lower LUFS bound and is flagged."""
    report = analyze_voice_seam(quiet_audio, [_phrase(0, 0.0, 5.0, "hello")], 6.0)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.LOUDNESS_SEAM in codes


def test_voice_seam_loudness_seam_clean_when_within_bounds(loud_audio):
    report = analyze_voice_seam(loud_audio, [_phrase(0, 0.0, 5.0, "hello")], 6.0)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.LOUDNESS_SEAM not in codes


def test_voice_seam_pitch_proxy_unavailable_is_honest_by_default(speech_audio):
    """No pitch provider is wired, so the report records the limitation honestly."""
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.PITCH_PROXY_UNAVAILABLE in codes
    pitch = next(f for f in report.findings if f.code is VoiceSeamFindingCode.PITCH_PROXY_UNAVAILABLE)
    assert pitch.detector == "kinocut.voice_seam.v1.pitch_proxy"


# --------------------------------------------------------------------------- #
# 4. Speaker identity provider (pluggable, capability-gated, never fake)
# --------------------------------------------------------------------------- #


def test_voice_seam_no_speaker_provider_returns_capability_unavailable(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.CAPABILITY_UNAVAILABLE
    assert report.speaker_identity.provider_id == "kinocut.voice_seam.none"
    assert report.speaker_identity.similarity_score is None
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH not in codes


def test_voice_seam_speaker_provider_never_fakes_identity_when_absent(speech_audio):
    """No provider ever synthesizes a name, label, or score — only `None`."""
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    assert report.speaker_identity.reference_label is None
    assert report.speaker_identity.similarity_score is None


def test_voice_seam_0519_like_identity_mismatch_produces_finding(speech_audio):
    """The canonical 0.519 similarity falls below the default threshold."""
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_MismatchSpeaker(),
    )
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.IDENTIFIED
    assert report.speaker_identity.similarity_score == 0.519
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH in codes


def test_voice_seam_matching_speaker_produces_no_mismatch_finding(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_MatchingSpeaker(),
    )
    assert report.speaker_identity.similarity_score == pytest.approx(0.92)
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH not in codes


def test_voice_seam_failing_speaker_provider_fails_soft(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_FailingSpeaker(),
    )
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.PROVIDER_FAILED
    codes = {finding.code for finding in report.findings}
    assert VoiceSeamFindingCode.SPEAKER_PROVIDER_FAILED in codes
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH not in codes


def test_voice_seam_speaker_identity_threshold_is_respected(speech_audio):
    """A 0.6 similarity with threshold 0.7 is a mismatch; threshold 0.5 is not."""
    provider = _SixtyPctSpeaker()
    report_strict = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=provider,
        identity_threshold=0.7,
    )
    report_loose = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=provider,
        identity_threshold=0.5,
    )
    strict_codes = {f.code for f in report_strict.findings}
    loose_codes = {f.code for f in report_loose.findings}
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH in strict_codes
    assert VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH not in loose_codes


@pytest.mark.parametrize(
    "kwargs",
    [
        {"identity_threshold": float("nan")},
        {"identity_threshold": -0.1},
        {"identity_threshold": 1.1},
        {"pace_bounds": (float("nan"), 240.0)},
        {"cadence_bounds": (60.0, 5.0)},
        {"loudness_bounds": (-10.0, -23.0)},
        {"silence_seam_seconds": float("inf")},
    ],
)
def test_voice_seam_rejects_non_finite_or_unordered_thresholds(speech_audio, kwargs):
    with pytest.raises(MCPVideoError) as exc:
        analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0, **kwargs)
    assert exc.value.code == "invalid_voice_seam_parameter"


def test_voice_seam_sanitizes_hostile_provider_id_on_failure(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_HostileIdFailingSpeaker(),
    )
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.PROVIDER_FAILED
    assert report.speaker_identity.provider_id == "kinocut.voice_seam.provider_failed"


def test_voice_seam_revalidates_constructed_provider_result(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_ConstructedHostileResultSpeaker(),
    )
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.PROVIDER_FAILED
    assert report.speaker_identity.provider_id == "test.speaker.hostile_result"
    assert "/private/provider/path" not in json.dumps(report.model_dump(mode="json"))


def test_voice_seam_fails_soft_when_provider_id_property_raises(speech_audio):
    report = analyze_voice_seam(
        speech_audio,
        [_phrase(0, 0.0, 3.0, "hi")],
        6.0,
        speaker_provider=_RaisingIdSpeaker(),
    )
    assert report.speaker_identity.availability is SpeakerIdentityAvailability.PROVIDER_FAILED
    assert report.speaker_identity.provider_id == "kinocut.voice_seam.provider_failed"


# --------------------------------------------------------------------------- #
# 5. Privacy / public-safe report
# --------------------------------------------------------------------------- #


def test_voice_seam_report_excludes_raw_transcript_text(speech_audio):
    text = "top secret transcript content"
    segments = [_phrase(0, 0.0, 3.0, text)]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    payload = json.dumps(report.model_dump(mode="json"))
    assert "top secret" not in payload
    assert "transcript content" not in payload


def test_voice_seam_report_excludes_host_paths(speech_audio, tmp_path):
    segments = [_phrase(0, 0.0, 3.0, "hi")]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    payload = json.dumps(report.model_dump(mode="json"))
    assert speech_audio not in payload
    assert str(tmp_path) not in payload
    assert os.path.expanduser("~") not in payload


def test_voice_seam_report_rejects_speaker_pii_at_construction():
    """A provider that leaks a real name/email must be rejected at construction."""
    with pytest.raises(Exception):
        SpeakerIdentityResult(
            provider_id="test.speaker.pii",
            availability=SpeakerIdentityAvailability.IDENTIFIED,
            similarity_score=0.9,
            reference_label="Jane Doe <jane@example.com>",
        )


def test_voice_seam_report_audio_fingerprint_is_sha256(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    fp = report.audio_fingerprint
    assert fp.startswith("sha256:")
    assert len(fp) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in fp[len("sha256:") :])  # type: ignore[index]


# --------------------------------------------------------------------------- #
# 6. Tamper / idempotency / determinism
# --------------------------------------------------------------------------- #


def test_voice_seam_same_input_yields_same_report(speech_audio):
    segments = [_phrase(0, 0.0, 3.0, "first"), _phrase(1, 3.0, 6.0, "second")]
    r1 = analyze_voice_seam(speech_audio, segments, 6.0)
    r2 = analyze_voice_seam(speech_audio, segments, 6.0)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_voice_seam_report_is_immutable(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    with pytest.raises(Exception):
        report.audio_fingerprint = "tampered"  # type: ignore[misc]
    with pytest.raises(Exception):
        report.findings = ()  # type: ignore[misc]


def test_voice_seam_input_segments_are_not_mutated(speech_audio):
    segments = [_phrase(0, 0.0, 6.0, "hello"), _phrase(1, 6.0, 9.0, "post-eof")]
    snapshot = [dict(s) for s in segments]
    analyze_voice_seam(speech_audio, segments, 6.0)
    assert [dict(s) for s in segments] == snapshot


def test_voice_seam_missing_audio_file_fails_closed(tmp_path):
    missing = str(tmp_path / "does-not-exist.wav")
    with pytest.raises(MCPVideoError):
        analyze_voice_seam(missing, [_phrase(0, 0.0, 3.0, "hi")], 6.0)


# --------------------------------------------------------------------------- #
# 7. Result shape and typing
# --------------------------------------------------------------------------- #


def test_voice_seam_report_has_required_composed_fields(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    assert isinstance(report, AudioSeamReport)
    assert isinstance(report.transcript_timing, TranscriptTimingSummary)
    assert isinstance(report.voice_style, VoiceStyleReport)
    assert isinstance(report.loudness, LoudnessSummary)
    assert isinstance(report.speaker_identity, SpeakerIdentityResult)
    assert isinstance(report.findings, tuple)
    assert report.analyzer_version.startswith("kinocut.voice_seam.")


def test_voice_seam_every_finding_carries_detector_and_bounded_severity(speech_audio):
    text = " ".join(["word"] * 200)
    segments = [_phrase(0, 0.0, 6.0, text)]
    report = analyze_voice_seam(speech_audio, segments, 6.0)
    assert report.findings, "expected at least one finding for the outlier input"
    for finding in report.findings:
        assert isinstance(finding, VoiceSeamFinding)
        assert isinstance(finding.code, VoiceSeamFindingCode)
        assert isinstance(finding.severity, VoiceSeamSeverity)
        assert finding.detector.startswith("kinocut.voice_seam.")
        start, end = finding.time_range
        assert 0.0 <= start <= end


def test_voice_seam_metric_value_object_carries_unit(speech_audio):
    report = analyze_voice_seam(speech_audio, [_phrase(0, 0.0, 3.0, "hi")], 6.0)
    for metric in report.voice_style.metrics:
        assert isinstance(metric, VoiceSeamMetric)
        assert metric.unit
        assert isinstance(metric.value, float)


def test_voice_seam_finding_code_enum_is_closed():
    expected = {
        "pace_outlier",
        "cadence_outlier",
        "silence_seam",
        "loudness_seam",
        "voice_identity_mismatch",
        "pitch_proxy_unavailable",
        "speaker_provider_failed",
        "transcript_empty",
    }
    assert {code.value for code in VoiceSeamFindingCode} == expected
