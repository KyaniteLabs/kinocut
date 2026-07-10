"""Additive extension contracts built on the immutable rescue v1 kernel."""

from .capabilities import extend_capability_snapshot
from .models import (
    ApprovalBinding,
    ExecutorCapability,
    FeatureIntent,
    IntentPlanEnvelope,
    ModelCapability,
    PolicyPermissions,
    PolicyProfile,
    PolicyRef,
    PreviewDiff,
    PreviewPair,
)
from .policy_registry import POLICY_REGISTRY, PolicyRegistry
from .preview_diff import bind_approval, build_preview_diff
from .verifier_registry import VerifierDefinition, VerifierRegistry

__all__ = [
    "POLICY_REGISTRY",
    "ApprovalBinding",
    "ExecutorCapability",
    "FeatureIntent",
    "IntentPlanEnvelope",
    "ModelCapability",
    "PolicyPermissions",
    "PolicyProfile",
    "PolicyRef",
    "PolicyRegistry",
    "PreviewDiff",
    "PreviewPair",
    "VerifierDefinition",
    "VerifierRegistry",
    "bind_approval",
    "build_preview_diff",
    "extend_capability_snapshot",
]
