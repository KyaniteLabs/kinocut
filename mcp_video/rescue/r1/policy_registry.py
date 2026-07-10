"""Immutable registry for separately versioned feature policies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .models import PolicyPermissions, PolicyProfile

PolicyKey = tuple[str, int]


class PolicyRegistry:
    def __init__(self, profiles: Iterable[PolicyProfile] = ()) -> None:
        indexed: dict[PolicyKey, PolicyProfile] = {}
        for profile in profiles:
            key = (profile.id, profile.version)
            if key in indexed:
                raise ValueError(f"duplicate policy profile: {profile.id}@{profile.version}")
            indexed[key] = profile
        self._profiles = MappingProxyType(indexed)

    @property
    def profiles(self) -> Mapping[PolicyKey, PolicyProfile]:
        return self._profiles

    def resolve(self, policy_id: str, version: int) -> PolicyProfile:
        try:
            return self._profiles[(policy_id, version)]
        except KeyError as exc:
            raise KeyError(f"unknown policy profile: {policy_id}@{version}") from exc

    def extend(self, *profiles: PolicyProfile) -> PolicyRegistry:
        return PolicyRegistry((*self._profiles.values(), *profiles))


POLICY_REGISTRY = PolicyRegistry(
    (
        PolicyProfile(
            id="local_content_preserving",
            version=1,
            description="Local-only rescue with timeline, crop, synthesis, network, and overwrite locked.",
            permissions=PolicyPermissions(),
            gating_checks=(),
        ),
        PolicyProfile(
            id="local_timeline_editing",
            version=1,
            description="Approved source-backed timeline edits without synthesis or network use.",
            permissions=PolicyPermissions(timeline=True),
            gating_checks=(
                "approval_hash",
                "source_coverage",
                "ordering",
                "approved_removal_only",
                "audio_video_sync",
                "caption_remap",
            ),
        ),
        PolicyProfile(
            id="local_visual_transform",
            version=1,
            description="Approved local spatial transforms with the source timeline locked.",
            permissions=PolicyPermissions(crop=True),
            gating_checks=(
                "subject_coverage",
                "safe_zone_coverage",
                "crop_continuity",
                "crop_resolution",
                "motion_reduction",
                "borders",
                "duration_and_sync",
            ),
        ),
        PolicyProfile(
            id="local_restorative",
            version=1,
            description="Evidence-gated local restoration without creative or timeline changes.",
            permissions=PolicyPermissions(),
            gating_checks=("restoration_feature_gates", "timeline_unchanged"),
        ),
        PolicyProfile(
            id="local_composition",
            version=1,
            description="Approved source-backed local composition and spatial layout.",
            permissions=PolicyPermissions(timeline=True, crop=True),
            gating_checks=(
                "source_attribution",
                "timeline_coverage",
                "audio_mix",
                "text_layout",
                "branding",
                "variant_contracts",
                "package_integrity",
            ),
        ),
        PolicyProfile(
            id="local_creative_autopilot",
            version=1,
            description="Local coordination of proven planners with synthesis and network locked.",
            permissions=PolicyPermissions(timeline=True, crop=True),
            gating_checks=(
                "prerequisite_capabilities",
                "approval_binding",
                "source_attribution",
                "package_integrity",
            ),
        ),
        PolicyProfile(
            id="explicit_remote_execution",
            version=1,
            description="Separately approved network execution that cannot broaden creative intent.",
            permissions=PolicyPermissions(network=True),
            gating_checks=(
                "egress_approval",
                "credential_redaction",
                "intent_unchanged",
                "local_download_verification",
            ),
        ),
    )
)
