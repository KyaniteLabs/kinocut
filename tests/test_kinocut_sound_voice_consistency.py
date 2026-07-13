"""RED-first tests for S10 voice consistency package.

Covers W5.1-W5.6 and preserved G18/G19 D42 ports:
* Versioned voice profile library (save/load/list/digest).
* Consistency checking via fake D42 style port.
* A/B reel construction referencing reference + render hashes.
* Cross-episode drift detection + realign surface.
* Batch regeneration on profile update.
* Cross-character distinctiveness and collision flagging.
* No real network calls; no local paths/credentials in repr.
"""

from __future__ import annotations

import struct
import tempfile
from collections.abc import Iterable

import pytest

from kinocut_sound import (
    AudioFormat,
    ChannelLayout,
    ConversionPolicy,
    Cue,
    CueKind,
    DeliveryPolicy,
    DeterminismClass,
    DitherPolicy,
    Emotion,
    Line,
    PlanProvenance,
    ProfileRef,
    Prosody,
    RenderFingerprint,
    Routing,
    SampleFormat,
    SoundPlan,
    TimeBase,
    Timeline,
)
from kinocut_sound.voice import (
    BatchPlanner,
    LocalSynthesisAdapter,
    default_roster,
)
from kinocut_sound.voice_consistency import (
    FakeD42Port,
    ProfileLibrary,
    VoiceProfile,
    build_ab_reel,
    default_fake_d42_port,
    detect_collisions,
    detect_cross_episode_drift,
    realign,
    regenerate_for_profile,
    spectral_distance,
    style_check,
)
from kinocut_sound.voice_consistency.d42_port import UnavailableStyleAdapter
from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_D42_UNAVAILABLE,
    CONSISTENCY_LIBRARY_INVALID,
    VoiceConsistencyError,
)


# --- Helpers -----------------------------------------------------------------


def _format() -> AudioFormat:
    return AudioFormat(
        channel_layout=ChannelLayout.MONO,
        sample_rate_hz=22050,
        sample_format=SampleFormat.PCM_S16LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.NONE,
    )


def _fingerprint() -> RenderFingerprint:
    return RenderFingerprint(
        determinism_class=DeterminismClass.SIGNAL_EQUIVALENT,
        seed="seed_1",
        locale="en-US",
        hardware_backend="local_synth",
        concurrency_ordering="serial",
        components=(
            {"role": "voice_roster", "digest": "sha256:" + "a" * 64},
            {"role": "tts_adapter", "digest": "sha256:" + "b" * 64},
        ),
    )


def _profile(
    *,
    profile_id: str = "hero_profile",
    version: int = 1,
    slot_id: str = "hero_tenor",
    reference_hash: str = "sha256:" + "c" * 64,
    consent_grant_ref: str = "consent_hero_1",
) -> VoiceProfile:
    return VoiceProfile(
        profile_id=profile_id,
        version=version,
        slot_id=slot_id,
        reference_hash=reference_hash,
        provenance=PlanProvenance(),
        defaults=Prosody(),
        fingerprint=_fingerprint(),
        consent_grant_ref=consent_grant_ref,
    )


def _line(
    *,
    line_id: str,
    profile_id: str = "hero_profile",
    version: int = 1,
    text_seed: str = "a",
    text_length_chars: int = 18,
    slot_id: str = "hero_tenor",
) -> Line:
    return Line(
        line_id=line_id,
        character_id="hero",
        profile=ProfileRef(profile_id=profile_id, version=version),
        text_hash="sha256:" + (text_seed * 64)[:64],
        text_length_chars=text_length_chars,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="medium_room",
        inherit_loudness=True,
    )


def _plan(
    lines: Iterable[Line] | tuple[Line, ...],
    *,
    project_id: str = "proj_a",
    episode_id: str = "ep_1",
) -> SoundPlan:
    return SoundPlan(
        project_id=project_id,
        episode_id=episode_id,
        format=_format(),
        timeline=Timeline(
            cues=(
                Cue(
                    cue_id="cue_intro",
                    start_seconds=0.0,
                    duration_seconds=1.0,
                    kind=CueKind.SILENCE,
                    source_ref="silence/room_tone.wav",
                ),
            ),
        ),
        lines=tuple(lines) if not isinstance(lines, tuple) else lines,
        beds=(),
        layers=(),
        routing=Routing(),
        delivery=DeliveryPolicy(),
        provenance=PlanProvenance(),
        created_by="tool:test",
    )


def _render_output_for_slot(slot_id: str, text_seed: str = "a") -> bytes:
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    slot = roster.get(slot_id)
    line = _line(line_id="ref", slot_id=slot_id, text_seed=text_seed)
    output = adapter.render(slot=slot, line=line)
    return output.wav_bytes


def _rms(wav_bytes: bytes) -> float:
    samples = _pcm_samples(wav_bytes)
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _pcm_samples(wav_bytes: bytes) -> tuple[int, ...]:
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[20:22] == struct.pack("<H", 1)  # PCM
    channel_count = struct.unpack_from("<H", wav_bytes, 22)[0]
    struct.unpack_from("<I", wav_bytes, 24)[0]
    bits_per_sample = struct.unpack_from("<H", wav_bytes, 34)[0]
    assert channel_count == 1
    assert bits_per_sample == 16
    data_offset = wav_bytes.find(b"data")
    assert data_offset > 0
    data_size = struct.unpack_from("<I", wav_bytes, data_offset + 4)[0]
    start = data_offset + 8
    count = data_size // 2
    return tuple(struct.unpack_from("<h", wav_bytes, start + i * 2)[0] for i in range(count))


# --- W5.1: Versioned voice profile library -----------------------------------


def test_profile_construction_and_fields():
    profile = _profile()
    assert profile.profile_id == "hero_profile"
    assert profile.version == 1
    assert profile.slot_id == "hero_tenor"
    assert profile.reference_hash.startswith("sha256:")
    assert profile.consent_grant_ref == "consent_hero_1"


def test_profile_rejects_invalid_codes_and_versions():
    with pytest.raises((ValueError, VoiceConsistencyError)):
        _profile(profile_id="has space")
    with pytest.raises((ValueError, VoiceConsistencyError)):
        _profile(version=0)
    with pytest.raises((ValueError, VoiceConsistencyError)):
        _profile(slot_id="/abs/path")


def test_profile_repr_does_not_leak_paths_or_credentials():
    profile = _profile()
    text = repr(profile)
    assert "/" not in text
    assert "secret" not in text.lower()
    assert "password" not in text.lower()
    assert "sha256:" in text  # hashes are safe


def test_library_save_and_load_latest_version():
    library = ProfileLibrary()
    v1 = _profile(version=1)
    v2 = _profile(version=2)
    library.save(v1)
    library.save(v2)
    loaded = library.load("hero_profile")
    assert loaded.version == 2


def test_library_load_specific_version():
    library = ProfileLibrary()
    v1 = _profile(version=1)
    v2 = _profile(version=2)
    library.save(v1)
    library.save(v2)
    assert library.load("hero_profile", version=1).version == 1
    assert library.load("hero_profile", version=2).version == 2


def test_library_list_sorted_versions():
    library = ProfileLibrary()
    library.save(_profile(version=1))
    library.save(_profile(version=3))
    library.save(_profile(version=2))
    versions = library.list("hero_profile")
    assert versions == (1, 2, 3)


def test_library_digest_stable_and_version_sensitive():
    library_a = ProfileLibrary()
    library_a.save(_profile(version=1))
    library_b = ProfileLibrary()
    library_b.save(_profile(version=1))
    assert library_a.digest() == library_b.digest()
    library_b.save(_profile(version=2))
    assert library_a.digest() != library_b.digest()


def test_library_unknown_profile_raises():
    library = ProfileLibrary()
    with pytest.raises(VoiceConsistencyError) as exc:
        library.load("missing")
    assert exc.value.code == CONSISTENCY_LIBRARY_INVALID


def test_library_rejects_overwrite_same_version():
    library = ProfileLibrary()
    library.save(_profile(version=1))
    with pytest.raises(VoiceConsistencyError) as exc:
        library.save(_profile(version=1))
    assert exc.value.code == CONSISTENCY_LIBRARY_INVALID


# --- W5.2: Consistency checking + G18/G19 D42 fake port ----------------------


def test_fake_d42_port_probes_available():
    port = default_fake_d42_port()
    style_probe, identity_probe = port.probe()
    assert style_probe.available is True
    assert identity_probe.available is True


def test_style_check_returns_perfect_similarity_for_identical_hashes():
    port = default_fake_d42_port()
    audio_hash = "sha256:" + "1" * 64
    result = style_check(
        port=port,
        profile_id="hero_profile",
        audio_hash=audio_hash,
        reference_hash=audio_hash,
    )
    assert result.similarity == pytest.approx(1.0)
    assert result.drift is False


def test_style_check_flags_drift_when_similarity_below_threshold():
    port = default_fake_d42_port()
    audio_hash = "sha256:" + "a" * 64
    reference_hash = "sha256:" + "b" * 64
    result = style_check(
        port=port,
        profile_id="hero_profile",
        audio_hash=audio_hash,
        reference_hash=reference_hash,
        threshold=0.95,
    )
    assert result.drift is True
    assert result.similarity < 0.95


def test_identity_check_returns_high_similarity_for_same_audio():
    port = default_fake_d42_port()
    audio_hash = "sha256:" + "a" * 64
    from kinocut_sound.voice_consistency.d42_port import IdentityCheckSpec

    result = port.identity.compare_identity(IdentityCheckSpec(audio_hash_a=audio_hash, audio_hash_b=audio_hash))
    assert result.similarity == pytest.approx(1.0)


def test_style_check_refuses_unavailable_port():
    unavailable = FakeD42Port(
        style=UnavailableStyleAdapter(),
        identity=default_fake_d42_port().identity,
    )
    with pytest.raises(VoiceConsistencyError) as exc:
        style_check(
            port=unavailable,
            profile_id="hero_profile",
            audio_hash="sha256:" + "a" * 64,
            reference_hash="sha256:" + "a" * 64,
        )
    assert exc.value.code == CONSISTENCY_D42_UNAVAILABLE


# --- W5.3: A/B reel ----------------------------------------------------------


def test_ab_reel_references_both_hashes():
    ref_hash = "sha256:" + "c" * 64
    new_hash = "sha256:" + "d" * 64
    reel = build_ab_reel(reference_hash=ref_hash, render_hash=new_hash, label="hero_line_1")
    assert reel.reference_hash == ref_hash
    assert reel.render_hash == new_hash
    assert reel.reel_label == "hero_line_1"
    assert reel.reel_hash.startswith("sha256:")
    assert reel.human_review_required is True


def test_ab_reel_repr_does_not_leak_paths():
    reel = build_ab_reel(
        reference_hash="sha256:" + "c" * 64,
        render_hash="sha256:" + "d" * 64,
        label="hero_line_1",
    )
    text = repr(reel)
    assert "/" not in text
    assert "secret" not in text.lower()


# --- W5.4: Drift detection across episodes -----------------------------------


def test_drift_detection_flags_low_similarity_across_episodes():
    profile = _profile(slot_id="hero_tenor")
    episodes = (
        _plan((_line(line_id="l1", text_seed="a"),), episode_id="ep_1"),
        _plan((_line(line_id="l2", text_seed="b"),), episode_id="ep_2"),
    )
    report = detect_cross_episode_drift(
        profile=profile,
        episodes=episodes,
        port=default_fake_d42_port(),
        threshold=1.0,  # identical required, so different text hashes drift
    )
    assert len(report.events) > 0
    assert report.has_drift is True
    first = report.events[0]
    assert first.episode_id in {"ep_1", "ep_2"}
    assert first.profile_id == profile.profile_id


def test_realign_returns_profile_with_bumped_version():
    profile = _profile(version=1)
    realigned = realign(profile, reference_wav_hash="sha256:" + "e" * 64)
    assert realigned.version == 2
    assert realigned.reference_hash == "sha256:" + "e" * 64
    assert realigned.profile_id == profile.profile_id


def test_realign_preserves_slot_and_consent():
    profile = _profile(slot_id="villain_baritone", consent_grant_ref="consent_v_1")
    realigned = realign(profile, reference_wav_hash="sha256:" + "e" * 64)
    assert realigned.slot_id == "villain_baritone"
    assert realigned.consent_grant_ref == "consent_v_1"


# --- W5.5: Batch regeneration on profile update ------------------------------


def _profile_slot_resolver(line, roster):
    """Map profile ids used in tests onto compiled roster slots."""
    mapping = {
        "hero_profile": "hero_tenor",
        "side_profile": "sidekick_tenor",
    }
    slot_id = mapping.get(line.profile.profile_id, line.profile.profile_id)
    return roster.get(slot_id)


def test_regenerate_for_profile_renders_lines_referencing_profile():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp,
            slot_resolver=_profile_slot_resolver,
        )
        plan = _plan(
            (
                _line(line_id="l1", profile_id="hero_profile"),
                _line(line_id="l2", profile_id="hero_profile"),
                _line(line_id="l3", profile_id="side_profile"),
            )
        )
        report = regenerate_for_profile(
            profile_id="hero_profile",
            episodes=(plan,),
            planner=planner,
        )
        assert report.profile_id == "hero_profile"
        assert len(report.rendered_clips) == 2
        assert {c.line_id for c in report.rendered_clips} == {"l1", "l2"}


def test_regenerate_is_deterministic_across_runs():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="l1", profile_id="hero_profile"),))
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        planner_a = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp_a,
            slot_resolver=_profile_slot_resolver,
        )
        planner_b = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp_b,
            slot_resolver=_profile_slot_resolver,
        )
        report_a = regenerate_for_profile(
            profile_id="hero_profile",
            episodes=(plan,),
            planner=planner_a,
        )
        report_b = regenerate_for_profile(
            profile_id="hero_profile",
            episodes=(plan,),
            planner=planner_b,
        )
        assert report_a.plan_hashes == report_b.plan_hashes
        assert tuple(c.output_hash for c in report_a.rendered_clips) == tuple(
            c.output_hash for c in report_b.rendered_clips
        )


# --- W5.6: Cross-character distinctiveness -----------------------------------


def test_spectral_distance_is_low_for_same_slot_different_text():
    wav_a = _render_output_for_slot("hero_tenor", text_seed="a")
    wav_b = _render_output_for_slot("hero_tenor", text_seed="b")
    dist = spectral_distance(wav_a, wav_b)
    assert 0.0 <= dist < 0.5


def test_spectral_distance_is_high_for_different_slots():
    wav_hero = _render_output_for_slot("hero_tenor", text_seed="a")
    wav_villain = _render_output_for_slot("villain_baritone", text_seed="a")
    dist = spectral_distance(wav_hero, wav_villain)
    assert dist > 0.1


def test_detect_collisions_flags_near_identical_signals():
    wav = _render_output_for_slot("hero_tenor", text_seed="a")
    pairs = (
        ("hero_tenor", wav),
        ("impostor", wav),
    )
    report = detect_collisions(pairs, threshold=0.02)
    assert report.has_collision is True
    assert len(report.collisions) >= 1


def test_detect_collisions_no_false_positives_for_distinct_slots():
    wav_hero = _render_output_for_slot("hero_tenor", text_seed="a")
    wav_villain = _render_output_for_slot("villain_baritone", text_seed="a")
    pairs = (
        ("hero_tenor", wav_hero),
        ("villain_baritone", wav_villain),
    )
    report = detect_collisions(pairs, threshold=0.05)
    assert report.has_collision is False
    assert len(report.collisions) == 0


# --- Package surface ---------------------------------------------------------


def test_voice_consistency_package_has_bounded_public_surface():
    from kinocut_sound import voice_consistency as vc

    public = set(vc.__all__)
    expected = {
        "VoiceProfile",
        "ProfileLibrary",
        "FakeD42Port",
        "default_fake_d42_port",
        "style_check",
        "build_ab_reel",
        "detect_cross_episode_drift",
        "realign",
        "detect_collisions",
        "spectral_distance",
        "regenerate_for_profile",
        "VoiceConsistencyError",
        "CONSISTENCY_D42_UNAVAILABLE",
        "CONSISTENCY_DRIFT_DETECTED",
        "CONSISTENCY_LIBRARY_INVALID",
        "CONSISTENCY_PROFILE_INVALID",
    }
    assert expected <= public
