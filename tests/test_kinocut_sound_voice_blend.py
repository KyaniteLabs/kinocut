"""RED-first tests for consent-gated voice blending (S6, W1.3)."""

from __future__ import annotations

import hashlib
import pytest

from kinocut_sound import Emotion, Line, ProfileRef, Prosody
from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
    DerivativeDisposition,
    LeaseStatus,
    RevocationPolicy,
)
from kinocut_sound.consent import (
    BlendAuthorization,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)
from kinocut_sound.voice import (
    LocalSynthesisAdapter,
    SynthesisOutput,
    VoiceError,
)

_SHA = "sha256:" + "b" * 64
_NOW = "2026-07-13T12:00:00Z"
_LATER = "2027-01-01T00:00:00Z"


def _scope(**overrides) -> ConsentScope:
    base = dict(
        project_ids=("proj_a",),
        character_ids=("char_a",),
        operations=("voice_clone", "voice_blend"),
        provider_classes=("local",),
        territory="US",
    )
    base.update(overrides)
    return ConsentScope(**base)


def _grant(
    grant_id: str,
    *,
    state: ConsentState = ConsentState.LIVE,
    blend: BlendAuthorization | None = None,
    operations: tuple[str, ...] = ("voice_clone", "voice_blend"),
) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id=f"subject_{grant_id}",
        rightsholder_id=f"rights_{grant_id}",
        scope=_scope(operations=operations),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso=_LATER,
        state=state,
        retention=RetentionPolicy(
            biometric_retention="quarantine_on_revocation",
            audit_retention="keep_5y",
        ),
        blend=blend,
    )


def _line(text_seed: str = "blend") -> Line:
    return Line(
        line_id="line_blend_1",
        character_id="char_a",
        profile=ProfileRef(profile_id="blend_composite_a", version=1),
        text_hash="sha256:" + (hashlib.sha256(text_seed.encode()).hexdigest()),
        text_length_chars=24,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="medium_room",
        inherit_loudness=True,
    )


def _ledger() -> ConsentLedger:
    return ConsentLedger(max_lease_seconds=60)


def _blend_context() -> AuthorizationContext:
    return AuthorizationContext(
        operation="voice_blend",
        project_id="proj_a",
        character_id="char_a",
        provider_class="local",
        territory="US",
    )


# ---------------------------------------------------------------------------
# BlendProfile
# ---------------------------------------------------------------------------


def test_blend_profile_requires_two_or_three_sources():
    from kinocut_sound.voice.blend import BlendProfile, BlendSource

    BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
            BlendSource(profile_id="clone_c", grant_id="grant_c", eq_preset="bright"),
        ),
    )
    with pytest.raises(VoiceError):
        BlendProfile(
            profile_id="blend_composite_a",
            composite_subject_id="subject_blend_a",
            composite_grant_id="grant_blend",
            sources=(
                BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            ),
        )
    with pytest.raises(VoiceError):
        BlendProfile(
            profile_id="blend_composite_a",
            composite_subject_id="subject_blend_a",
            composite_grant_id="grant_blend",
            sources=tuple(
                BlendSource(profile_id=f"clone_{i}", grant_id=f"grant_{i}", eq_preset="neutral")
                for i in range(4)
            ),
        )


def test_blend_profile_requires_unique_source_grant_ids():
    from kinocut_sound.voice.blend import BlendProfile, BlendSource

    with pytest.raises(VoiceError):
        BlendProfile(
            profile_id="blend_composite_a",
            composite_subject_id="subject_blend_a",
            composite_grant_id="grant_blend",
            sources=(
                BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
                BlendSource(profile_id="clone_b", grant_id="grant_a", eq_preset="warm"),
            ),
        )


def test_blend_profile_repr_does_not_leak_paths_or_credentials():
    from kinocut_sound.voice.blend import BlendProfile, BlendSource

    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    text = repr(profile)
    assert "/home/" not in text
    assert "password" not in text.lower()
    assert "api_key" not in text.lower()


# ---------------------------------------------------------------------------
# BlendRenderer — generation boundary
# ---------------------------------------------------------------------------


def _registered_blend_ledger() -> tuple[ConsentLedger, BlendAuthorization]:
    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.register_grant(_grant("grant_b"), at_iso=_NOW, actor_id="reviewer_001")
    blend = BlendAuthorization(
        source_grant_ids=("grant_a", "grant_b"),
        composite_subject_id="subject_blend_a",
    )
    ledger.register_grant(
        _grant("grant_blend", blend=blend, operations=("voice_blend",)),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    return ledger, blend


def test_blend_render_succeeds_with_live_source_and_composite_grants():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger, blend = _registered_blend_ledger()
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    output = renderer.render(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_blend_context(),
        at_iso=_NOW,
    )
    assert isinstance(output, SynthesisOutput)
    assert output.output_hash.startswith("sha256:")


def test_blend_render_fails_closed_when_composite_grant_missing():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.register_grant(_grant("grant_b"), at_iso=_NOW, actor_id="reviewer_001")
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend_missing",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_blend_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_missing"


def test_blend_render_fails_closed_when_source_grant_revoked():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger = _ledger()
    ledger.register_grant(
        _grant("grant_a", state=ConsentState.REVOKED),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    ledger.register_grant(_grant("grant_b"), at_iso=_NOW, actor_id="reviewer_001")
    blend = BlendAuthorization(
        source_grant_ids=("grant_a", "grant_b"),
        composite_subject_id="subject_blend_a",
    )
    ledger.register_grant(
        _grant("grant_blend", blend=blend, operations=("voice_blend",)),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_blend_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_revoked"


# ---------------------------------------------------------------------------
# Blend receipt lineage
# ---------------------------------------------------------------------------


def test_blend_render_receipt_contains_every_source_grant_plus_composite():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger, blend = _registered_blend_ledger()
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    receipt = renderer.render_receipt(
        line=_line(),
        profile=profile,
        ledger=ledger,
        context=_blend_context(),
        at_iso=_NOW,
    )
    assert set(receipt.consent_grant_refs) == {"grant_a", "grant_b", "grant_blend"}


# ---------------------------------------------------------------------------
# Per-source EQ
# ---------------------------------------------------------------------------


def test_blend_per_source_eq_changes_output_hash():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger, blend = _registered_blend_ledger()
    profile_a = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="neutral"),
        ),
    )
    profile_b = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="bright"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    out_a = renderer.render(
        line=_line(),
        profile=profile_a,
        ledger=ledger,
        context=_blend_context(),
        at_iso=_NOW,
    )
    out_b = renderer.render(
        line=_line(),
        profile=profile_b,
        ledger=ledger,
        context=_blend_context(),
        at_iso=_NOW,
    )
    assert out_a.output_hash != out_b.output_hash


def test_blend_unknown_eq_preset_fails_closed():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger, blend = _registered_blend_ledger()
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="unknown_preset_xyz"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="neutral"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(VoiceError) as exc:
        renderer.render(
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_blend_context(),
            at_iso=_NOW,
        )
    assert "preset" in exc.value.code or "eq" in exc.value.code


# ---------------------------------------------------------------------------
# Revocation race: acquire lease, revoke WAIT, commit quarantines derivative
# ---------------------------------------------------------------------------


def test_blend_revocation_race_quarantines_derivative():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger, blend = _registered_blend_ledger()
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())

    lease = renderer.acquire_blend_lease(
        profile=profile,
        ledger=ledger,
        context=_blend_context(),
        at_iso="2026-07-13T12:00:01Z",
        ttl_seconds=30,
        actor_id="worker_001",
    )
    assert lease.status is LeaseStatus.ACTIVE

    result = ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.WAIT,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="reviewer_001",
    )
    assert result.pending is True

    lineage = renderer.commit_blend_lease(
        lease_id=lease.lease_id,
        output_asset_id="asset_blend_1",
        profile=profile,
        ledger=ledger,
        at_iso="2026-07-13T12:00:03Z",
        actor_id="worker_001",
    )
    assert "grant_a" in lineage.direct_grant_ids
    assert "grant_b" in lineage.direct_grant_ids
    assert "grant_blend" in lineage.direct_grant_ids

    outcome = ledger.outcome_for("asset_blend_1")
    assert outcome.disposition is DerivativeDisposition.QUARANTINE


# ---------------------------------------------------------------------------
# Export boundary
# ---------------------------------------------------------------------------


def test_blend_export_fails_closed_without_live_grant():
    from kinocut_sound.voice.blend import BlendProfile, BlendRenderer, BlendSource

    ledger = _ledger()
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.register_grant(
        _grant("grant_b", state=ConsentState.REVOKED),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    blend = BlendAuthorization(
        source_grant_ids=("grant_a", "grant_b"),
        composite_subject_id="subject_blend_a",
    )
    ledger.register_grant(
        _grant("grant_blend", blend=blend, operations=("voice_blend",)),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    profile = BlendProfile(
        profile_id="blend_composite_a",
        composite_subject_id="subject_blend_a",
        composite_grant_id="grant_blend",
        sources=(
            BlendSource(profile_id="clone_a", grant_id="grant_a", eq_preset="neutral"),
            BlendSource(profile_id="clone_b", grant_id="grant_b", eq_preset="warm"),
        ),
    )
    renderer = BlendRenderer(adapter=LocalSynthesisAdapter())
    with pytest.raises(AuthorizationError) as exc:
        renderer.export(
            output_path="blend/char_a/line_1.wav",
            output_dir="/tmp/ignored_for_test",
            line=_line(),
            profile=profile,
            ledger=ledger,
            context=_blend_context(),
            at_iso=_NOW,
        )
    assert exc.value.code == "grant_revoked"
