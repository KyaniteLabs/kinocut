"""RED-first tests for the ``kinocut_sound`` ConsentGrant contract.

A ConsentGrant records a subject's right-to-clone authorization. Subject
identity is an opaque bounded id; biometric material, prompts, and transcripts
are referenced by hash only; an explicit cloud-egress grant names provider,
data classes, territory, retention ceiling, and expiry. State transitions are
compare-before-replace: revocation blocks new leases; a revoked grant never
re-authorizes a cache hit. This leaf owns the contract shape; the ledger,
race handling, and quarantine belong to the S2 leaf.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.consent import (
    AuditEvent,
    BlendAuthorization,
    CloudEgressGrant,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)


_SHA = "sha256:" + "0" * 64


def _scope(**overrides) -> ConsentScope:
    base = dict(
        project_ids=("proj-alpha",),
        character_ids=("character_a",),
        operations=("voice_clone",),
        provider_classes=("local",),
        territory="US",
    )
    base.update(overrides)
    return ConsentScope(**base)


def test_consent_states_are_closed():
    assert {s.value for s in ConsentState} == {"live", "expired", "revoked", "missing"}


def test_consent_scope_rejects_unbounded_codes_and_unsafe_text():
    scope = _scope()
    assert scope.territory == "US"
    for field in ("project_ids", "character_ids", "operations", "provider_classes"):
        with pytest.raises(ValidationError):
            kwargs = {"territory": "US", field: ("with space",)}
            all_fields = dict(
                project_ids=("p",),
                character_ids=("c",),
                operations=("o",),
                provider_classes=("l",),
            )
            all_fields.update(kwargs)
            ConsentScope(**all_fields)
    with pytest.raises(ValidationError):
        _scope(intended_use_summary="/etc/passwd is a path")
    with pytest.raises(ValidationError):
        _scope(intended_use_summary="x" * 201)


def test_retention_policy_rejects_unbounded_codes():
    RetentionPolicy(biometric_retention="delete_after_use", audit_retention="keep_5y")
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            RetentionPolicy(biometric_retention=bad, audit_retention="keep_5y")


def test_consent_grant_records_provenance_by_hash_not_value():
    grant = ConsentGrant(
        grant_id="grant_001",
        subject_id="subject_001",
        rightsholder_id="rightsholder_001",
        scope=_scope(),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(biometric_retention="delete_after_use", audit_retention="keep_5y"),
        audit_log=(AuditEvent(event="issued", at_iso="2026-01-01T00:00:00Z", actor="reviewer_001"),),
    )
    assert grant.grant_id == "grant_001"
    assert grant.subject_id == "subject_001"
    assert grant.scope.intended_use_summary is None
    assert grant.state is ConsentState.LIVE


def test_consent_grant_rejects_unbounded_subject_and_ids():
    base = dict(
        rightsholder_id="rh_001",
        scope=_scope(),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="rev_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(biometric_retention="delete_after_use", audit_retention="keep_5y"),
    )
    for bad in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            ConsentGrant(grant_id=bad, subject_id="subj", **base)
        with pytest.raises(ValidationError):
            ConsentGrant(grant_id="g", subject_id=bad, **base)


def test_consent_grant_rejects_expiry_before_issue():
    with pytest.raises(ValidationError):
        ConsentGrant(
            grant_id="g",
            subject_id="s",
            rightsholder_id="rh",
            scope=_scope(),
            reference_evidence_hash=_SHA,
            transcript_evidence_hash=_SHA,
            reviewer_id="r",
            issue_iso="2027-01-01T00:00:00Z",
            expiry_iso="2026-01-01T00:00:00Z",
            state=ConsentState.LIVE,
            retention=RetentionPolicy(biometric_retention="delete_after_use", audit_retention="keep_5y"),
        )


def test_cloud_egress_grant_requires_provider_data_and_territory():
    CloudEgressGrant(
        provider_id="elevenlabs",
        data_classes=("reference_audio", "embedding"),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso="2027-01-01T00:00:00Z",
    )
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            CloudEgressGrant(
                provider_id=bad,
                data_classes=("reference_audio",),
                territory="US",
                retention_ceiling_days=30,
                expiry_iso="2027-01-01T00:00:00Z",
            )
    with pytest.raises(ValidationError):
        CloudEgressGrant(
            provider_id="elevenlabs",
            data_classes=(),  # at least one data class required
            territory="US",
            retention_ceiling_days=30,
            expiry_iso="2027-01-01T00:00:00Z",
        )


def test_blend_authorization_records_per_source_grants():
    BlendAuthorization(
        source_grant_ids=("grant_a", "grant_b"),
        composite_subject_id="subject_blend_001",
    )
    with pytest.raises(ValidationError):
        BlendAuthorization(
            source_grant_ids=("grant_a",),  # blend requires at least 2 sources
            composite_subject_id="subj",
        )
    with pytest.raises(ValidationError):
        BlendAuthorization(
            source_grant_ids=("grant_a", "grant_a"),  # unique sources
            composite_subject_id="subj",
        )
