from __future__ import annotations

from mcp_video.rescue.models import VerificationCheck
from mcp_video.rescue.verifier import CHECK_IDS
from mcp_video.rescue.r1.models import (
    FeatureIntent,
    IntentPlanEnvelope,
    PolicyPermissions,
    PolicyProfile,
    PolicyRef,
)
from mcp_video.rescue.r1.policy_registry import POLICY_REGISTRY
from mcp_video.rescue.r1.verifier_registry import VerifierDefinition, VerifierRegistry


def test_toy_non_rescue_extension_preserves_rescue_v1_bytes(rescue_plan) -> None:
    baseline = rescue_plan.model_dump_json().encode()
    toy_policy = PolicyProfile(
        id="toy_visual_crop",
        version=1,
        description="Synthetic acceptance profile.",
        permissions=PolicyPermissions(crop=True),
        gating_checks=("toy_crop_bounds",),
    )
    policies = POLICY_REGISTRY.extend(toy_policy)
    verifiers = VerifierRegistry(
        (
            VerifierDefinition(
                id="toy_crop_bounds",
                run=lambda _: VerificationCheck(id="toy_crop_bounds", passed=True, message="Crop remains in bounds."),
            ),
        )
    )

    envelope = IntentPlanEnvelope.create(
        base_plan=rescue_plan,
        policy=PolicyRef(id=toy_policy.id, version=toy_policy.version),
        intent=FeatureIntent(
            feature_id="toy_visual_crop",
            action_ids=("crop:subject",),
            payload={"crop_tracks": [{"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}]},
        ),
        verifier_ids=toy_policy.gating_checks,
    )

    assert policies.resolve("toy_visual_crop", 1) == toy_policy
    assert tuple(item.id for item in verifiers.resolve_with_mandatory(envelope.verifier_ids)) == (
        *CHECK_IDS,
        "toy_crop_bounds",
    )
    assert envelope.base_plan.model_dump_json().encode() == baseline
    assert POLICY_REGISTRY.resolve("local_content_preserving", 1).permissions.crop is False
