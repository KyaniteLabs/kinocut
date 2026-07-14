"""RED-first tests for the ``kinocut_sound`` receipt contract.

A sound receipt reuses the repository's edit-receipt v1 shape and adds the
sound-specific additive section: SoundPlan hash, profile versions used, consent
grant references, and loudness/true-peak verification. Absolute source paths,
prompts, transcripts, credentials, and subject PII are structurally excluded:
they are unrepresentable in the receipt's bounded codes and hashes. The whole
section embeds under a single additive ``sound`` key on an unchanged v1 receipt.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.receipt import (
    LoudnessVerification,
    OrderedInput,
    PreservationProof,
    SoundReceipt,
    SoundReceiptSection,
    Transformation,
)


_SHA = "sha256:" + "0" * 64


def test_ordered_input_rejects_host_path_role_and_unbounded_prose():
    OrderedInput(
        asset_id=_SHA,
        input_hash=_SHA,
        in_point=0.0,
        out_point=1.0,
        probed_duration=1.0,
        role="dialog_clip",
        safe_display_name="line_001",
    )
    for bad in ("with space", "../x", "https://x"):
        with pytest.raises(ValidationError):
            OrderedInput(
                asset_id=_SHA,
                input_hash=_SHA,
                role=bad,
                safe_display_name="x",
            )
    for bad in ("/etc/passwd", "~/home", "https://host/x"):
        with pytest.raises(ValidationError):
            OrderedInput(
                asset_id=_SHA,
                input_hash=_SHA,
                role="ok",
                safe_display_name=bad,
            )


def test_ordered_input_rejects_out_of_order_points_and_non_numeric():
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_SHA,
            input_hash=_SHA,
            in_point=1.0,
            out_point=0.5,
            role="ok",
            safe_display_name="x",
        )
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_SHA,
            input_hash=_SHA,
            in_point="0.5",  # type: ignore[arg-type]
            role="ok",
            safe_display_name="x",
        )


def test_transformation_rejects_unbounded_codes_and_paths():
    Transformation(
        tool="ffmpeg",
        operation="loudness_normalize",
        params_hash=_SHA,
        toolchain_versions=("ffmpeg_6.0", "kinocut_sound_0.1.0"),
        output_duration=12.0,
        output_hash=_SHA,
        warnings=(),
    )
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            Transformation(tool=bad, operation="loudness_normalize")
    for bad in ("/etc/passwd",):
        with pytest.raises(ValidationError):
            Transformation(tool="ffmpeg", operation=bad)


def test_preservation_proof_requires_bounded_expected_and_method():
    PreservationProof(
        expected="duration_authoritative",
        method="probe_duration",
        source_fingerprint=_SHA,
        output_fingerprint=_SHA,
        verdict="preserved",
    )
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            PreservationProof(
                expected=bad,
                method="probe_duration",
                source_fingerprint=_SHA,
                output_fingerprint=_SHA,
                verdict="preserved",
            )
    with pytest.raises(ValidationError):
        PreservationProof(
            expected="duration",
            method="probe",
            source_fingerprint=_SHA,
            output_fingerprint=_SHA,
            verdict="unknown_verdict",
        )


def test_loudness_verification_captures_measurement_and_pass_state():
    LoudnessVerification(
        preset="stream_-14",
        integrated_lufs=-14.02,
        true_peak_dbtp=-1.05,
        lra_lu=7.5,
        within_tolerance=True,
    )
    with pytest.raises(ValidationError):
        LoudnessVerification(
            preset="stream_-14",
            integrated_lufs=0.0,
            true_peak_dbtp=-1.0,
            lra_lu=7.5,
            within_tolerance=True,
        )


def test_sound_receipt_section_carries_plan_hash_and_grant_refs_only():
    section = SoundReceiptSection(
        plan_hash=_SHA,
        profile_versions=(("voice_a", 1),),
        consent_grant_refs=("grant_001",),
        loudness=LoudnessVerification(
            preset="stream_-14",
            integrated_lufs=-14.0,
            true_peak_dbtp=-1.0,
            lra_lu=7.0,
            within_tolerance=True,
        ),
        ordered_inputs=(OrderedInput(asset_id=_SHA, input_hash=_SHA, role="dialog", safe_display_name="line_001"),),
        transformations=(),
        preservation_proofs=(),
        warnings=(),
        human_review_required=True,
    )
    assert section.consent_grant_refs == ("grant_001",)
    # No subject identity or PII field is representable.
    import kinocut_sound.receipt as r

    field_names = set(r.SoundReceiptSection.model_fields.keys())
    assert "subject_id" not in field_names
    assert "biometric" not in field_names
    assert "raw_prompt" not in field_names


def test_sound_receipt_wraps_legacy_v1_and_attaches_additive_sound_section():
    legacy = {
        "schema_version": 1,
        "operation": "video_edit",
        "normalized_parameters": {"preset": "standard"},
        "inputs": [],
        "output_hash": _SHA,
        "warnings": [],
    }
    section = SoundReceiptSection(
        plan_hash=_SHA,
        profile_versions=(),
        consent_grant_refs=(),
        loudness=LoudnessVerification(
            preset="stream_-14",
            integrated_lufs=-14.0,
            true_peak_dbtp=-1.0,
            lra_lu=7.0,
            within_tolerance=True,
        ),
        human_review_required=False,
    )
    receipt = SoundReceipt.from_legacy(legacy, section)
    assert receipt.schema_version == 1
    assert receipt.operation == "video_edit"
    assert receipt.sound.plan_hash == _SHA
    serialized = receipt.model_dump_json()
    assert "sound" in serialized
    # The legacy normalized_parameters are canonical-hashed, never stored raw.
    # ``normalized_parameters`` (the raw dict key) must NOT be a key in the
    # serialized form — only ``normalized_parameters_hash`` appears.
    import json as _json

    payload = _json.loads(serialized)
    assert "normalized_parameters" not in payload
    assert "normalized_parameters_hash" in payload
    assert receipt.normalized_parameters_hash is not None
    assert receipt.normalized_parameters_hash.startswith("sha256:")
    # The raw value must not leak through serialization.
    assert "standard" not in serialized


def test_sound_receipt_rejects_unbounded_operation_and_legacy_path_leakage():
    with pytest.raises(ValidationError):
        SoundReceipt(
            schema_version=1,
            operation="with space",
            inputs=(),
            output_hash=_SHA,
            warnings=(),
            sound=SoundReceiptSection(
                plan_hash=_SHA,
                profile_versions=(),
                consent_grant_refs=(),
                loudness=LoudnessVerification(
                    preset="stream_-14",
                    integrated_lufs=-14.0,
                    true_peak_dbtp=-1.0,
                    lra_lu=7.0,
                    within_tolerance=True,
                ),
                human_review_required=False,
            ),
        )


def test_sound_receipt_rejects_raw_normalized_parameters_field():
    """The normalized_parameters field must be structurally unrepresentable."""
    with pytest.raises(ValidationError):
        SoundReceipt(
            schema_version=1,
            operation="video_edit",
            inputs=(),
            output_hash=_SHA,
            warnings=(),
            sound=SoundReceiptSection(
                plan_hash=_SHA,
                profile_versions=(),
                consent_grant_refs=(),
                loudness=LoudnessVerification(
                    preset="stream_-14",
                    integrated_lufs=-14.0,
                    true_peak_dbtp=-1.0,
                    lra_lu=7.0,
                    within_tolerance=True,
                ),
                human_review_required=False,
            ),
            normalized_parameters={"secret": "leaks"},  # type: ignore[call-arg]
        )


def _section() -> SoundReceiptSection:
    return SoundReceiptSection(
        plan_hash=_SHA,
        profile_versions=(),
        consent_grant_refs=(),
        loudness=LoudnessVerification(
            preset="stream_-14",
            integrated_lufs=-14.0,
            true_peak_dbtp=-1.0,
            lra_lu=7.0,
            within_tolerance=True,
        ),
        human_review_required=False,
    )


def test_from_legacy_does_not_store_raw_normalized_parameters():
    """from_legacy hashes normalized_parameters; raw values never serialize."""
    hostile = {
        "api_key": "sk-1234567890abcdef",
        "aws_key": "AKIAIOSFODNN7EXAMPLE",
        "password": "secret123",
        "host_path": "/etc/passwd",
        "email": "user@example.com",
        "subject_pii": "subject_001",
        "raw_prompt": "clone this voice",
    }
    legacy = {
        "schema_version": 1,
        "operation": "episode_render",
        "normalized_parameters": hostile,
        "inputs": [],
        "output_hash": _SHA,
        "warnings": [],
    }
    receipt = SoundReceipt.from_legacy(legacy, _section())
    serialized = receipt.model_dump_json()
    # None of the hostile content may appear in the serialized receipt.
    for forbidden in hostile.values():
        assert str(forbidden) not in serialized
    # Keys from the raw dict must not appear either.
    for key in hostile:
        assert key not in serialized
    # The raw field name must not be a key in the serialized JSON (the hash
    # field name ``normalized_parameters_hash`` is the only ``normalized_*``
    # key present).
    import json as _json

    payload = _json.loads(serialized)
    assert "normalized_parameters" not in payload
    # The hash is present instead.
    assert receipt.normalized_parameters_hash is not None
    assert receipt.normalized_parameters_hash.startswith("sha256:")


def test_from_legacy_recursively_hashes_nested_pii_without_storing_raw():
    """Deeply nested PII inside normalized_parameters must not leak."""
    hostile = {
        "config": {
            "nested": {
                "deep_path": "/home/user/secret.key",
                "credential": "password123",
                "email": "admin@corp.com",
            }
        }
    }
    legacy = {
        "schema_version": 1,
        "operation": "episode_render",
        "normalized_parameters": hostile,
        "inputs": [],
        "output_hash": _SHA,
        "warnings": [],
    }
    receipt = SoundReceipt.from_legacy(legacy, _section())
    serialized = receipt.model_dump_json()
    assert "/home/user/secret.key" not in serialized
    assert "password123" not in serialized
    assert "admin@corp.com" not in serialized
    assert "credential" not in serialized
    assert "config" not in serialized
    import json as _json

    payload = _json.loads(serialized)
    assert "normalized_parameters" not in payload


def test_from_legacy_preserves_explicit_hash_over_raw_parameters():
    """If legacy already carries normalized_parameters_hash, it wins."""
    legacy = {
        "schema_version": 1,
        "operation": "episode_render",
        "normalized_parameters": {"secret": "data"},
        "normalized_parameters_hash": _SHA,
        "inputs": [],
        "output_hash": _SHA,
        "warnings": [],
    }
    receipt = SoundReceipt.from_legacy(legacy, _section())
    assert receipt.normalized_parameters_hash == _SHA
    serialized = receipt.model_dump_json()
    assert "secret" not in serialized


def test_from_legacy_without_parameters_leaves_hash_unset():
    """A legacy receipt without normalized_parameters leaves hash as None."""
    legacy = {
        "schema_version": 1,
        "operation": "video_edit",
        "inputs": [],
        "output_hash": _SHA,
        "warnings": [],
    }
    receipt = SoundReceipt.from_legacy(legacy, _section())
    assert receipt.normalized_parameters_hash is None
