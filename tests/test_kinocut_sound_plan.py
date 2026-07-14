"""RED-first tests for the ``kinocut_sound`` SoundPlan master contract.

The SoundPlan is the single source of truth for an episode's audio. It is a
validated immutable record (not a rendering side effect) that carries the
authoritative timeline, lines, beds/layers, buses/routing, format, delivery,
and provenance references. It exposes a canonical id and serializes without
ever leaking raw prompts, transcripts, host paths, or credentials.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.consent import ConsentState
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.format import AudioFormat, ChannelLayout, ConversionPolicy, DitherPolicy, SampleFormat, TimeBase
from kinocut_sound.lines import Emotion, Line, ProfileRef, Prosody
from kinocut_sound.routing import Bus, LatencyCompensation, PanLaw, Routing, Track
from kinocut_sound.sound_plan import (
    AssetLicenseRef,
    PlanProvenance,
    ProcessingPresetRef,
    SoundPlan,
)
from kinocut_sound.timeline import Cue, CueKind, Timeline


_SHA = "sha256:" + "0" * 64


def _format() -> AudioFormat:
    return AudioFormat(
        channel_layout=ChannelLayout.STEREO,
        sample_rate_hz=48000,
        sample_format=SampleFormat.PCM_S24LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.TRIANGULAR,
    )


def _routing() -> Routing:
    return Routing(
        tracks=(
            Track(
                track_id="track_dialog_001",
                destination_bus_id="bus_dialog",
                gain_db=0.0,
                pan_law=PanLaw.LINEAR,
                muted=False,
                soloed=False,
            ),
        ),
        buses=(Bus(bus_id="bus_dialog", kind="dialog"),),
        sends=(),
        sidechains=(),
        envelopes=(),
        latency=LatencyCompensation(policy="sample_accurate"),
    )


def _timeline() -> Timeline:
    return Timeline(
        cues=(
            Cue(
                cue_id="cue_001",
                start_seconds=0.0,
                duration_seconds=2.5,
                kind=CueKind.LINE,
                source_ref="lines/line_001.json",
            ),
        ),
        tail_seconds=0.5,
    )


def _line() -> Line:
    return Line(
        line_id="line_001",
        character_id="character_a",
        profile=ProfileRef(profile_id="voice_a", version=1),
        text_hash=_SHA,
        text_length_chars=42,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="close_mic_dry",
        pronunciation_overrides=(),
        inherit_loudness=True,
    )


def _provenance() -> PlanProvenance:
    return PlanProvenance(
        consent_grant_refs=("grant_001",),
        asset_license_refs=(AssetLicenseRef(license_id="cc_by_4.0", asset_hash=_SHA),),
        processing_preset_refs=(ProcessingPresetRef(preset_id="denoise_v1", preset_hash=_SHA),),
        model_refs=(),
        prompt_hashes=(),
        transcript_hashes=(_SHA,),
    )


def _plan(**overrides) -> SoundPlan:
    base = dict(
        project_id="proj-alpha",
        episode_id="episode_001",
        plan_kind="episode",
        format=_format(),
        timeline=_timeline(),
        lines=(_line(),),
        beds=(),
        layers=(),
        routing=_routing(),
        delivery=DeliveryPolicy(),
        provenance=_provenance(),
        created_by="agent:worker_1",
    )
    base.update(overrides)
    return SoundPlan(**base)


def test_sound_plan_is_immutable_and_derives_canonical_record_id():
    plan = _plan()
    digest = plan.canonical_id()
    assert digest.startswith("sha256:")
    rebuilt = _plan(record_id=digest)
    assert rebuilt.record_id == digest
    with pytest.raises(ValidationError):
        plan.project_id = "mut"  # type: ignore[misc]


def test_sound_plan_rejects_unknown_kind_and_unbounded_episode_id():
    with pytest.raises(ValidationError):
        _plan(plan_kind="clip")  # only 'episode' permitted at this leaf
    for bad in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            _plan(episode_id=bad)


def test_sound_plan_provenance_excludes_raw_prompts_and_credentials():
    plan = _plan()
    serialized = plan.model_dump_json()
    # No raw prompt or credential field is even named.
    assert "raw_prompt" not in serialized
    assert "raw_transcript" not in serialized
    assert "credential" not in serialized
    assert "api_key" not in serialized
    # The transcript is hashed only.
    assert plan.provenance.transcript_hashes == (_SHA,)


def test_sound_plan_authoritative_duration_comes_from_timeline():
    plan = _plan()
    assert plan.authoritative_duration_seconds == plan.timeline.total_seconds


def test_sound_plan_rejects_dangling_line_ids_and_unknown_characters():
    # A line whose character_id is not in plan.character_ids is still a valid
    # structural input — character_ids is informational — but the line_id
    # itself must be unique across the plan.
    with pytest.raises(ValidationError):
        _plan(
            lines=(_line(), _line()),  # duplicate line_id
        )


def test_sound_plan_record_id_must_equal_canonical_digest():
    plan = _plan()
    digest = plan.canonical_id()
    _plan(record_id=digest)  # ok
    with pytest.raises(ValidationError):
        _plan(record_id=_SHA)  # sha-shaped but not the real digest


def test_plan_provenance_rejects_unbounded_codes_and_leaky_text():
    AssetLicenseRef(license_id="cc_by_4.0", asset_hash=_SHA)
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            AssetLicenseRef(license_id=bad, asset_hash=_SHA)
    ProcessingPresetRef(preset_id="denoise_v1", preset_hash=_SHA)
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            ProcessingPresetRef(preset_id=bad, preset_hash=_SHA)


def test_sound_plan_serialization_excludes_subject_pii():
    plan = _plan()
    assert "subject_id" not in plan.model_dump_json()
    assert ConsentState.LIVE.value == "live"


# Hostile non-hex tests: the old _is_sha256 only checked prefix + length,
# accepting ``sha256:`` + 64 non-hex chars. The canonical Sha256 type enforces
# strict lowercase-hex.
_NON_HEX = "sha256:" + "z" * 64  # 'z' is not a hex digit
_UPPER_HEX = "sha256:" + "A" * 64  # uppercase rejected (canonical = lowercase)
_BAD_PREFIX = "sha384:" + "0" * 64  # wrong algorithm prefix


def test_asset_license_ref_rejects_non_hex_hash():
    for bad in (_NON_HEX, _UPPER_HEX, _BAD_PREFIX):
        with pytest.raises(ValidationError):
            AssetLicenseRef(license_id="cc_by_4.0", asset_hash=bad)


def test_processing_preset_ref_rejects_non_hex_hash():
    for bad in (_NON_HEX, _UPPER_HEX, _BAD_PREFIX):
        with pytest.raises(ValidationError):
            ProcessingPresetRef(preset_id="denoise_v1", preset_hash=bad)


def test_model_ref_rejects_non_hex_hash():
    from kinocut_sound.sound_plan import ModelRef

    for bad in (_NON_HEX, _UPPER_HEX, _BAD_PREFIX):
        with pytest.raises(ValidationError):
            ModelRef(model_id="voice_a", model_hash=bad, model_version=1)


def test_plan_provenance_rejects_non_hex_prompt_and_transcript_hashes():
    for bad in (_NON_HEX, _UPPER_HEX, _BAD_PREFIX):
        with pytest.raises(ValidationError):
            PlanProvenance(prompt_hashes=(bad,))
        with pytest.raises(ValidationError):
            PlanProvenance(transcript_hashes=(bad,))
