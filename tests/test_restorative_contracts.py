from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_video.restorative import (
    CapabilityStatus,
    ModelProvenance,
    ModelRequirement,
    RestorativeCapability,
    RestorativeFeature,
    RestorativePlan,
    VERIFICATION_CONTRACTS,
    VerificationContract,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def test_plan_is_hash_bound_and_locks_external_side_effects() -> None:
    plan = RestorativePlan.create(
        feature=RestorativeFeature.FRAME_REPAIR,
        source_sha256=SHA_A,
        requested_executor_id="local.frame_repair",
        model_requirement=ModelRequirement(model_id="local.repair", version="1.0", sha256=SHA_B),
    )

    assert plan.plan_sha256.startswith("sha256:")
    assert plan.local_only is True
    assert plan.network_allowed is False
    assert plan.downloads_allowed is False
    assert plan.substitution_allowed is False
    assert plan.evidence_contract_id == "frame_repair.evidence.v1"
    assert plan.verification_contract_id == "frame_repair.verification.v1"
    forged = plan.model_dump(mode="json")
    forged["plan_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="plan hash"):
        RestorativePlan.model_validate(forged)


@pytest.mark.parametrize("field", ["network_allowed", "downloads_allowed", "substitution_allowed"])
def test_plan_rejects_relaxing_fail_closed_permissions(field: str) -> None:
    valid = RestorativePlan.create(
        feature=RestorativeFeature.SPEECH_DENOISE,
        source_sha256=SHA_A,
        requested_executor_id="local.denoise",
    )
    values = valid.model_dump(mode="json")
    values[field] = True

    with pytest.raises(ValidationError):
        RestorativePlan.model_validate(values)


def test_frame_repair_plan_requires_exact_model_identity() -> None:
    with pytest.raises(ValidationError, match="frame repair requires a model requirement"):
        RestorativePlan.create(
            feature=RestorativeFeature.FRAME_REPAIR,
            source_sha256=SHA_A,
            requested_executor_id="local.frame_repair",
        )


def test_local_model_provenance_cannot_be_a_url_or_absolute_path() -> None:
    with pytest.raises(ValidationError, match="relative local path"):
        ModelProvenance(
            model_id="local.repair",
            version="1.0",
            sha256=SHA_B,
            origin="local",
            loaded_from="https://models.example/repair.bin",
            determinism_scope="same model, executor, hardware, and inputs",
        )


@pytest.mark.parametrize("status", [CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNSUPPORTED])
def test_non_available_capability_requires_reason_and_exposes_no_substitute(status: CapabilityStatus) -> None:
    capability = RestorativeCapability(feature=RestorativeFeature.SPEECH_DENOISE, status=status, reason="not installed")

    assert capability.executor_id is None
    assert capability.model_provenance is None
    assert capability.substitute_executor_id is None


def test_verification_contracts_are_versioned_and_feature_specific() -> None:
    contract = VERIFICATION_CONTRACTS[RestorativeFeature.SPEECH_DENOISE]

    assert isinstance(contract, VerificationContract)
    assert contract.id == "speech_denoise.verification.v1"
    assert contract.version == 1
    assert contract.required_gate_ids == (
        "noise_reduced",
        "snr_non_regression",
        "intelligibility_preserved",
        "speech_coverage_preserved",
    )


def test_verification_contract_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        VERIFICATION_CONTRACTS[RestorativeFeature.SPEECH_DENOISE] = VERIFICATION_CONTRACTS[
            RestorativeFeature.STYLED_CAPTIONS
        ]
