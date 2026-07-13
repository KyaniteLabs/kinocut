"""RED-first tests for consent-gated zero-shot voice cloning (S6, W1.2)."""

from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

from kinocut_sound import Emotion, Line, ProfileRef, Prosody
from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
    GenerationLease,
    LeaseStatus,
    RevocationPolicy,
)
from kinocut_sound.consent import (
    CloudEgressGrant,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)
from kinocut_sound.voice import (
    CLOUD_NOT_ALLOWED,
    LocalSynthesisAdapter,
    SynthesisOutput,
    VoiceError,
    VoiceRoster,
    default_roster,
)

_SHA = "sha256:" + "a" * 64
_NOW = "2026-07-13T12:00:00Z"
_LATER = "2027-01-01T00:00:00Z"
_EARLIER = "2026-02-01T00:00:00Z"


def _scope(**overrides) -> ConsentScope:
    base = dict(
        project_ids=("proj_a",),
        character_ids=("char_a",),
        operations=("voice_clone",),
        provider_classes=("local",),
        territory="US",
    )
    base.update(overrides)
    return ConsentScope(**base)


def _grant(
    grant_id: str,
    *,
    state: ConsentState = ConsentState.LIVE,
    expiry_iso: str = _LATER,
    cloud: CloudEgressGrant | None = None,
    operations: tuple[str, ...] = ("voice_clone",),
    provider_classes: tuple[str, ...] = ("local",),
) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id=f"subject_{grant_id}",
        rightsholder_id=f"rights_{grant_id}",
        scope=_scope(operations=operations, provider_classes=provider_classes),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso=expiry_iso,
        state=state,
        retention=RetentionPolicy(
            biometric_retention="quarantine_on_revocation",
            audit_retention="keep_5y",
        ),
        cloud_egress=cloud,
    )


def _line(text_seed: str = "a", text_length_chars: int = 24) -> Line:
    return Line(
        line_id="line_1",
        character_id="char_a",
        profile=ProfileRef(profile_id="clone_subject_a", version=1),
        text_hash="sha256:" + (hashlib.sha256(text_seed.encode()).hexdigest()),
        text_length_chars=text_length_chars,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="medium_room",
        inherit_loudness=True,
    )


def _ledger() -> ConsentLedger:
    return ConsentLedger(max_lease_seconds=60)


def _live_clone_context() -> AuthorizationContext:
    return AuthorizationContext(
        operation="voice_clone",
        project_id="proj_a",
        character_id="char_a",
        provider_class="local",
        territory="US",
    )


def _cloud_context() -> AuthorizationContext:
    return AuthorizationContext(
        operation="voice_clone",
        project_id="proj_a",
        character_id="char_a",
        provider_class="cloud",
        territory="US",
    )


def _base_slot(roster: VoiceRoster | None = None) -> object:
    roster = roster or default_roster()
    return roster.get("hero_tenor")


# ---------------------------------------------------------------------------
# CloneProfile
# ---------------------------------------------------------------------------


def test_clone_profile_creation_with_live_grant_succeeds():
    from kinocut_sound.voice.clone import CloneProfile

    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    assert profile.profile_id == "clone_subject_a"
    assert profile.grant_id == "grant_a"


def test_clone_profile_repr_does_not_leak_paths_credentials_or_raw_text():
    from kinocut_sound.voice.clone import CloneProfile

    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    text = repr(profile)
    assert "/home/" not in text
    assert "password" not in text.lower()
    assert "api_key" not in text.lower()
    assert "secret transcript" not in text.lower()


# ---------------------------------------------------------------------------
# CloneRenderer — generation boundary
# ---------------------------------------------------------------------------


def test_clone_render_succeeds_with_live_grant_and_records_lineage():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    output = renderer.render(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_live_clone_context(),
        at_iso=_NOW,
    )
    assert isinstance(output, SynthesisOutput)
    assert output.output_hash.startswith("sha256:")


def test_clone_render_fails_closed_when_grant_missing():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_missing",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_missing"


def test_clone_render_fails_closed_when_grant_revoked():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", state=ConsentState.REVOKED),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_revoked"


def test_clone_render_fails_closed_when_grant_expired():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", expiry_iso=_EARLIER),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_expired"


def test_clone_render_fails_closed_when_revocation_is_pending():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=30,
        context=_live_clone_context(),
        at_iso="2026-07-13T12:00:01Z",
        actor_id="worker_001",
    )
    ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.WAIT,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso="2026-07-13T12:00:03Z",
        )
    assert exc.value.code == "revocation_pending"


# ---------------------------------------------------------------------------
# CloneRenderer — export boundary
# ---------------------------------------------------------------------------


def test_clone_export_succeeds_with_live_grant_and_writes_wav():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with tempfile.TemporaryDirectory() as tmp:
        rel_path = "clone/char_a/line_1.wav"
        full_path = os.path.join(tmp, *rel_path.split("/"))
        renderer.export(
            output_path=rel_path,
            output_dir=tmp,
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso=_NOW,
        )
        assert os.path.exists(full_path)


def test_clone_export_fails_closed_without_live_grant():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", state=ConsentState.REVOKED),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(AuthorizationError) as exc:
            renderer.export(
                output_path="clone/char_a/line_1.wav",
                output_dir=tmp,
                line=_line(),
                profile=profile,
                ledger=ledger,
                context=_live_clone_context(),
                at_iso=_NOW,
            )
        assert exc.value.code == "grant_revoked"


def test_clone_export_rejects_absolute_and_traversal_paths():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with tempfile.TemporaryDirectory() as tmp:
        for bad in ("/abs/path.wav", "../escape.wav", "a//b.wav"):
            with pytest.raises(VoiceError):
                renderer.export(
                    output_path=bad,
                    output_dir=tmp,
                    line=_line(),
                    profile=profile,
                    ledger=ledger,
                    context=_live_clone_context(),
                    at_iso=_NOW,
                )


# ---------------------------------------------------------------------------
# Determinism & cloud egress
# ---------------------------------------------------------------------------


def test_clone_render_is_deterministic_for_same_line_and_profile():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    out_a = renderer.render(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_live_clone_context(),
        at_iso=_NOW,
    )
    out_b = renderer.render(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_live_clone_context(),
        at_iso=_NOW,
    )
    assert out_a.output_hash == out_b.output_hash
    assert out_a.wav_bytes == out_b.wav_bytes


def test_clone_cloud_egress_denied_without_explicit_cloud_egress_grant():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", provider_classes=("local", "cloud")),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.authorize_cloud_egress(
            grant_ids=("grant_a",),
            provider_id="elevenlabs",
            data_classes=("reference_audio",),
            territory="US",
            retention_days=30,
            ledger=ledger,
            context=_cloud_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "cloud_egress_denied"


def test_clone_cloud_egress_succeeds_with_matching_cloud_egress_grant():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    cloud = CloudEgressGrant(
        provider_id="elevenlabs",
        data_classes=("reference_audio", "transcript"),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso=_LATER,
    )
    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", cloud=cloud, provider_classes=("local", "cloud")),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    authorized = renderer.authorize_cloud_egress(
        grant_ids=("grant_a",),
        provider_id="elevenlabs",
        data_classes=("reference_audio",),
        territory="US",
        retention_days=30,
        ledger=ledger,
        context=_cloud_context(),
        at_iso=_NOW,
    )
    assert authorized == ("grant_a",)


def test_clone_render_rejects_cloud_stub_without_explicit_authorization():
    from kinocut_sound.voice import CloudTtsAdapterStub
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=CloudTtsAdapterStub())
    with pytest.raises(VoiceError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_live_clone_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == CLOUD_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Generation lease integration
# ---------------------------------------------------------------------------


def test_clone_render_acquires_and_commits_generation_lease():
    from kinocut_sound.voice.clone import CloneProfile, CloneRenderer

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    profile = CloneProfile(
        profile_id="clone_subject_a",
        subject_id="subject_a",
        grant_id="grant_a",
        reference_hash=_SHA,
        transcript_hash=_SHA,
        base_slot=_base_slot(),
        created_at_iso=_NOW,
    )
    renderer = CloneRenderer(adapter=LocalSynthesisAdapter())
    output, lease_id = renderer.render_with_lease(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_live_clone_context(),
        at_iso=_NOW,
        ttl_seconds=30,
        actor_id="worker_001",
    )
    assert isinstance(output, SynthesisOutput)
    assert lease_id.startswith("lease_")
    lease = ledger._leases.get(lease_id)
    assert isinstance(lease, GenerationLease)
    assert lease.status is LeaseStatus.ACTIVE
