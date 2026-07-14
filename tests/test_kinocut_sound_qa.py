"""S11 QA and metadata leaf tests."""

from __future__ import annotations
import pytest
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.qa import (
    ChapterMarker,
    EpisodeQaSummary,
    FakeAsrPort,
    QaError,
    build_metadata,
    check_loudness,
    detect_artifacts,
    rollup_season,
    verify_script_asr,
)


def test_loudness_report_fields():
    wav = synthesize_tone(duration_seconds=0.3, amplitude=0.2, seed=1)
    report = check_loudness(wav, DeliveryPolicy())
    assert report.within_tolerance is True
    assert report.integrated_lufs < 0
    assert report.true_peak_dbtp < 0


def test_artifact_clean_tone_ok():
    wav = synthesize_tone(duration_seconds=0.3, amplitude=0.2, seed=2)
    rep = detect_artifacts(wav)
    assert rep.ok is True
    assert rep.click_count == 0


def test_artifact_detects_injected_click():
    from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
    from array import array

    wav = synthesize_tone(duration_seconds=0.2, amplitude=0.1, seed=3)
    samples, rate = parse_wav(wav)
    samples = array("h", samples)
    samples[50] = 32000
    samples[51] = -32000
    bad = pcm_to_wav(samples, sample_rate_hz=rate)
    with pytest.raises(QaError) as exc:
        detect_artifacts(bad, jump_threshold=10000)
    assert exc.value.code == "qa_artifact_detected"


def test_asr_fake_port_matches_script():
    port = FakeAsrPort()
    report = verify_script_asr(
        port=port,
        script_hashes=("sha256:" + "a" * 64, "sha256:" + "b" * 64),
        audio_duration_seconds=2.0,
    )
    assert report.ok is True
    assert report.mismatch_count == 0
    assert len(report.segments) == 2
    assert report.segments[-1].end_seconds <= 2.0 + 1e-9


def test_asr_unavailable_fails_closed():
    with pytest.raises(QaError) as exc:
        verify_script_asr(
            port=FakeAsrPort(available=False), script_hashes=("sha256:" + "a" * 64,), audio_duration_seconds=1.0
        )
    assert exc.value.code == "qa_unavailable"


def test_metadata_chapters_and_isrc():
    meta = build_metadata(
        title="Episode_One",
        duration_seconds=120.0,
        chapters=(ChapterMarker(title="cold_open", start_seconds=0.0),),
        credits=("writer_a",),
        isrc="USRC17607839",
        loudness_lufs=-14.0,
    )
    assert meta.title == "Episode_One"
    assert meta.chapters[0].title == "cold_open"
    assert meta.isrc == "USRC17607839"


def test_season_rollup():
    report = rollup_season(
        (
            EpisodeQaSummary(episode_id="ep1", loudness_ok=True, artifacts_ok=True),
            EpisodeQaSummary(episode_id="ep2", loudness_ok=False, artifacts_ok=True),
        )
    )
    assert report.episode_count == 2
    assert report.pass_count == 1
    assert report.fail_count == 1


def test_qa_public_surface():
    from kinocut_sound import qa

    assert "check_loudness" in qa.__all__
    assert "FakeAsrPort" in qa.__all__
