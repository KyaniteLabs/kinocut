"""Calibrated ports remain injectable; malformed backend evidence fails closed."""

from types import SimpleNamespace

import pytest

from kinocut.sound_joins.d42_bind import KinocutD42Port
from kinocut_sound.capability import CapabilityResult
from kinocut_sound.receipt import LoudnessVerification, SoundReceiptSection
from kinocut_sound.voice_consistency._errors import VoiceConsistencyError
from kinocut_sound.voice_consistency.d42_port import IdentityCheckResult, StyleCheckResult
from kinocut_sound.voice_consistency.metrics import identity_similarity, style_check


SHA = "sha256:" + "a" * 64


def _port(similarity):
    style = SimpleNamespace(
        probe=lambda: CapabilityResult(adapter_id="calibrated_style", available=True),
        check_style=lambda spec: StyleCheckResult(
            profile_id=spec.profile_id, similarity=similarity, drift=False, flags=()
        ),
    )
    identity = SimpleNamespace(
        probe=lambda: CapabilityResult(adapter_id="calibrated_identity", available=True),
        compare_identity=lambda spec: IdentityCheckResult(similarity=similarity, same_identity=False),
    )
    return KinocutD42Port(style=style, identity=identity)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9", 10**1000, -(10**1000)])
@pytest.mark.parametrize("kind", ["style", "identity"])
def test_nonfinite_out_of_range_or_coerced_backend_similarity_rejected(bad, kind):
    port = _port(bad)
    with pytest.raises(VoiceConsistencyError) as error:
        if kind == "style":
            style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA)
        else:
            identity_similarity(port=port, audio_hash_a=SHA, audio_hash_b=SHA)
    assert error.value.code == "consistency_metric_invalid"


def test_injected_calibrated_ports_preserve_actual_scores():
    port = _port(0.91)
    assert style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA).similarity == 0.91
    assert identity_similarity(port=port, audio_hash_a=SHA, audio_hash_b=SHA) == 0.91


def test_receipt_missing_loudness_requires_explicit_unmeasured_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SoundReceiptSection(plan_hash=SHA, loudness=None, human_review_required=True)
    section = SoundReceiptSection(
        plan_hash=SHA, loudness=None, loudness_assessment_status="not_evaluated", human_review_required=True
    )
    assert SoundReceiptSection.model_validate(section.model_dump()).loudness is None


def test_existing_measured_loudness_receipts_remain_strict_and_compatible():
    from pydantic import ValidationError

    evidence = LoudnessVerification(
        preset="stream_-14", integrated_lufs=-14, true_peak_dbtp=-2, lra_lu=1, within_tolerance=True
    )
    section = SoundReceiptSection(plan_hash=SHA, loudness=evidence, human_review_required=True)
    assert section.loudness_assessment_status == "measured"
    assert "loudness_assessment_status" not in section.model_dump()
    assert SoundReceiptSection.model_validate(section.model_dump()).loudness == evidence
    with pytest.raises(ValidationError):
        SoundReceiptSection(
            plan_hash=SHA, loudness=evidence, loudness_assessment_status="not_evaluated", human_review_required=True
        )


def test_legacy_measured_receipt_shape_and_identity_survive_nested_serialization():
    from kinocut_sound.receipt import SoundReceipt
    from kinocut_sound._canonical import canonical_digest
    from tests.sound_numeric_cases import model_case
    from tests.test_sound_numeric_guards import BASELINE

    name = "kinocut_sound.receipt.SoundReceiptSection"
    model, original_data = model_case(name)
    section = model.model_validate(original_data)
    assert canonical_digest(section) == BASELINE["model_hashes"][name]
    assert "loudness_assessment_status" not in section.model_dump(mode="json")
    parent = SoundReceipt(operation="voice_render", output_hash=SHA, sound=section)
    serialized = parent.model_dump(mode="json")
    assert "loudness_assessment_status" not in serialized["sound"]
    assert canonical_digest(parent) == canonical_digest(serialized)
    assert SoundReceipt.model_validate(serialized).sound.loudness_assessment_status == "measured"


def test_unmeasured_receipt_serialization_keeps_explicit_status_and_roundtrips():
    from kinocut_sound.receipt import SoundReceipt

    section = SoundReceiptSection(
        plan_hash=SHA, loudness=None, loudness_assessment_status="not_evaluated", human_review_required=True
    )
    parent = SoundReceipt(operation="voice_render", output_hash=SHA, sound=section)
    serialized = parent.model_dump(mode="json")
    assert serialized["sound"]["loudness"] is None
    assert serialized["sound"]["loudness_assessment_status"] == "not_evaluated"
    assert SoundReceipt.model_validate(serialized) == parent


@pytest.mark.parametrize(
    "update",
    [
        {"profile_id": "other"},
        {"flags": ("private/path",)},
        {"flags": tuple("ok" for _ in range(33))},
        {"flags": ["ok"]},
        {"drift": "False"},
    ],
)
def test_malformed_style_result_contract_rejected(update):
    port = _port(0.95)
    body = dict(profile_id="narrator", similarity=0.95, drift=False, flags=())
    body.update(update)
    port.style.check_style = lambda spec: StyleCheckResult(**body)
    with pytest.raises(VoiceConsistencyError):
        style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA)


def test_provider_detected_drift_is_not_discarded_by_similarity_threshold():
    port = _port(0.95)
    port.style.check_style = lambda spec: StyleCheckResult(profile_id="narrator", similarity=0.95, drift=True, flags=())
    result = style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA)
    assert result.drift
    assert "style_drift" in result.flags


def test_generated_drift_flag_cannot_overflow_output_limit():
    port = _port(0.1)
    port.style.check_style = lambda spec: StyleCheckResult(
        profile_id="narrator", similarity=0.1, drift=False, flags=tuple(f"flag_{index}" for index in range(32))
    )
    with pytest.raises(VoiceConsistencyError) as failure:
        style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA)
    assert failure.value.code == "consistency_metric_invalid"


def test_backend_drift_flag_is_not_duplicated():
    port = _port(0.1)
    port.style.check_style = lambda spec: StyleCheckResult(
        profile_id="narrator", similarity=0.1, drift=True, flags=("style_drift",)
    )
    assert style_check(port=port, profile_id="narrator", audio_hash=SHA, reference_hash=SHA).flags == ("style_drift",)
