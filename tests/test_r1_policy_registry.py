from __future__ import annotations

import pytest

from mcp_video.rescue.r1.models import PolicyPermissions, PolicyProfile
from mcp_video.rescue.r1.policy_registry import POLICY_REGISTRY, PolicyRegistry


def test_local_content_preserving_profile_is_explicit_and_immutable() -> None:
    profile = POLICY_REGISTRY.resolve("local_content_preserving", 1)

    assert profile.permissions == PolicyPermissions(
        timeline=False,
        crop=False,
        synthesis=False,
        network=False,
        source_overwrite=False,
    )
    with pytest.raises(TypeError):
        POLICY_REGISTRY.profiles[("local_content_preserving", 1)] = profile  # type: ignore[index]


def test_policy_registry_rejects_duplicate_versions() -> None:
    profile = PolicyProfile(
        id="toy_visual_crop",
        version=1,
        description="Toy crop policy.",
        permissions=PolicyPermissions(crop=True),
        gating_checks=("toy_crop_bounds",),
    )

    with pytest.raises(ValueError, match="duplicate policy profile"):
        PolicyRegistry((profile, profile))


@pytest.mark.parametrize(
    ("policy_id", "allowed", "required_check"),
    (
        ("local_timeline_editing", {"timeline"}, "approved_removal_only"),
        ("local_visual_transform", {"crop"}, "crop_continuity"),
        ("local_restorative", set(), "restoration_feature_gates"),
        ("local_composition", {"timeline", "crop"}, "source_attribution"),
        ("local_creative_autopilot", {"timeline", "crop"}, "prerequisite_capabilities"),
        ("explicit_remote_execution", {"network"}, "egress_approval"),
    ),
)
def test_post_rescue_policies_have_least_privilege_and_gating_checks(
    policy_id: str, allowed: set[str], required_check: str
) -> None:
    profile = POLICY_REGISTRY.resolve(policy_id, 1)
    permissions = profile.permissions.model_dump()

    assert {name for name, value in permissions.items() if value} == allowed
    assert required_check in profile.gating_checks
    assert profile.permissions.source_overwrite is False


def test_policy_gate_ids_match_semantic_and_visual_verifier_receipts() -> None:
    timeline = POLICY_REGISTRY.resolve("local_timeline_editing", 1)
    visual = POLICY_REGISTRY.resolve("local_visual_transform", 1)

    assert timeline.gating_checks == (
        "approval_hash",
        "source_coverage",
        "ordering",
        "approved_removal_only",
        "audio_video_sync",
        "caption_remap",
    )
    assert visual.gating_checks == (
        "subject_coverage",
        "safe_zone_coverage",
        "crop_continuity",
        "crop_resolution",
        "motion_reduction",
        "borders",
        "duration_and_sync",
    )
