"""Bed audition reel: labeled equal-duration sections under the real voice (#24).

The planning layer is unit-tested everywhere. The render layer requires FFmpeg
and immutable source snapshots and is exercised by the CI-gated integration
test, exactly like ``test_audio_bed.py``.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from kinocut.audio_engine.audition import (
    AuditionPlan,
    plan_bed_audition,
)
from kinocut.errors import MCPVideoError
from kinocut.source_identity import immutable_verified_snapshot_available


def _write(path, name: str) -> str:
    p = path / name
    p.write_bytes(b"\x00")
    return str(p)


@pytest.fixture
def voice(tmp_path):
    return _write(tmp_path, "voice.wav")


@pytest.fixture
def beds(tmp_path):
    return [_write(tmp_path, f"bed{i}.wav") for i in range(3)]


# --- pure planning layer (runs everywhere) ---


def test_plan_assigns_equal_duration_sections_with_default_labels(voice, beds):
    plan = plan_bed_audition(voice, beds, section_seconds=4.0)
    assert isinstance(plan, AuditionPlan)
    assert [s.label for s in plan.sections] == ["Bed 1", "Bed 2", "Bed 3"]
    assert [s.duration_seconds for s in plan.sections] == [4.0, 4.0, 4.0]
    assert [s.voice_start_seconds for s in plan.sections] == [0.0, 4.0, 8.0]
    assert [s.voice_end_seconds for s in plan.sections] == [4.0, 8.0, 12.0]


def test_plan_accepts_explicit_unique_labels(voice, beds):
    plan = plan_bed_audition(voice, beds[:2], labels=["Calm", "Driving"], section_seconds=2.0)
    assert [s.label for s in plan.sections] == ["Calm", "Driving"]


def test_plan_rejects_label_count_mismatch(voice, beds):
    with pytest.raises(MCPVideoError, match="label"):
        plan_bed_audition(voice, beds, labels=["only-one"], section_seconds=2.0)


def test_plan_rejects_duplicate_labels(voice, beds):
    with pytest.raises(MCPVideoError, match="unique"):
        plan_bed_audition(voice, beds[:2], labels=["Same", "Same"], section_seconds=2.0)


def test_plan_rejects_empty_candidates(voice):
    with pytest.raises(MCPVideoError, match="at least one"):
        plan_bed_audition(voice, [], section_seconds=2.0)


def test_plan_rejects_duplicate_candidate_paths(voice, tmp_path):
    dup = _write(tmp_path, "same.wav")
    with pytest.raises(MCPVideoError, match="distinct"):
        plan_bed_audition(voice, [dup, dup], section_seconds=2.0)


def test_plan_rejects_nonpositive_section_seconds(voice, beds):
    with pytest.raises(MCPVideoError, match="positive"):
        plan_bed_audition(voice, beds, section_seconds=0.0)


def test_plan_rejects_invalid_mix_policy(voice, beds):
    # target_lufs is bounded; an out-of-range value must fail at planning time.
    with pytest.raises(MCPVideoError):
        plan_bed_audition(voice, beds, section_seconds=2.0, target_lufs=999.0)


def test_plan_mix_policy_defaults_match_ship_level(voice, beds):
    plan = plan_bed_audition(voice, beds, section_seconds=2.0)
    # The audition reuses the audio_bed ship-level mix policy defaults.
    assert plan.mix_policy["target_lufs"] == -16.0
    assert plan.mix_policy["loop"] is True


# --- CI-gated integration test for the render layer ---


pytestmark_render = [
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
    pytest.mark.skipif(
        not immutable_verified_snapshot_available(),
        reason="immutable verified source snapshots are unavailable",
    ),
]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
@pytest.mark.skipif(
    not immutable_verified_snapshot_available(),
    reason="immutable verified source snapshots are unavailable",
)
def test_render_bed_audition_produces_labeled_reel(tmp_path):
    from kinocut.audio_engine.audition import bed_audition

    def _ffmpeg(args: list[str]) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, capture_output=True, timeout=60)

    voice = tmp_path / "voice.wav"
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:d=6", str(voice)])
    bed_a = tmp_path / "bed_a.wav"
    bed_b = tmp_path / "bed_b.wav"
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=110:sample_rate=44100:d=3", str(bed_a)])
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:d=3", str(bed_b)])

    out = tmp_path / "audition.wav"
    receipt = bed_audition(
        str(voice), [str(bed_a), str(bed_b)], str(out),
        labels=["Calm", "Bright"], section_seconds=3.0,
        output_display_name="audition",
    )
    assert out.exists()
    assert receipt["operation"] == "bed_audition"
    assert [s["label"] for s in receipt["sections"]] == ["Calm", "Bright"]
    assert receipt["output_duration_seconds"] == pytest.approx(6.0, abs=0.25)
    assert receipt["voice_content_sha256"].startswith("sha256:")
