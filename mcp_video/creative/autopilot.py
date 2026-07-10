"""A1 coordinator over declared proven pure planners, with no hidden fallback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .autopilot_models import (
    AutopilotAbstention,
    AutopilotPolicy,
    AutopilotRequest,
    AutopilotResult,
    PlannerCapability,
)
from .composition import _validated, _validated_sequence, plan_composition
from .errors import CreativeContractError
from .manifest import select_assets
from .models import ProjectManifest, canonical_digest
from .preview import build_composition_preview

AUTOPILOT_REQUIRED_CAPABILITIES = (
    "planner:asset_selection",
    "planner:composition",
    "planner:preview",
)
_ZERO_SHA256 = "sha256:" + "0" * 64


def _result(
    *,
    manifest: ProjectManifest,
    request: AutopilotRequest,
    policy: AutopilotPolicy,
    capabilities: tuple[PlannerCapability, ...],
    capability_ids: tuple[str, ...],
    plan=None,
    preview=None,
    abstentions: tuple[AutopilotAbstention, ...] = (),
) -> AutopilotResult:
    capability_index = {item.id: item for item in capabilities}
    draft = AutopilotResult(
        request_id=request.id,
        manifest_sha256=manifest.manifest_sha256,
        request_sha256=canonical_digest(request, exclude=set()),
        policy_sha256=canonical_digest(policy, exclude=set()),
        policy_id=policy.id,
        status="abstained" if abstentions else "planned",
        capability_ids=capability_ids,
        capability_bindings=tuple(
            f"{capability_id}@{capability_index[capability_id].version}"
            if capability_id in capability_index
            else f"{capability_id}@missing"
            for capability_id in capability_ids
        ),
        plan=plan,
        preview=preview,
        abstentions=abstentions,
        autopilot_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"autopilot_sha256": canonical_digest(draft, exclude={"autopilot_sha256"})})


def _capability_abstentions(
    required_ids: tuple[str, ...],
    capabilities: tuple[PlannerCapability, ...],
    policy: AutopilotPolicy,
    request_permissions: tuple[str, ...],
) -> tuple[AutopilotAbstention, ...]:
    indexed: dict[str, PlannerCapability] = {}
    for capability in capabilities:
        if capability.id in indexed:
            raise CreativeContractError(
                "duplicate_planner_capability", f"Planner capability {capability.id} is declared more than once."
            )
        indexed[capability.id] = capability
    abstentions: list[AutopilotAbstention] = []
    required_permissions = set(request_permissions)
    for capability_id in required_ids:
        capability = indexed.get(capability_id)
        if capability is None:
            abstentions.append(
                AutopilotAbstention(
                    code="capability_missing",
                    subject=capability_id,
                    message="A required planner capability was not declared.",
                )
            )
            continue
        required_permissions.update(capability.required_permissions)
        if not capability.available:
            abstentions.append(
                AutopilotAbstention(
                    code="capability_unavailable",
                    subject=capability_id,
                    message="The declared planner capability is unavailable.",
                )
            )
        if not capability.proven:
            abstentions.append(
                AutopilotAbstention(
                    code="capability_not_proven",
                    subject=capability_id,
                    message="The declared planner capability has no proven contract.",
                )
            )
        if not capability.deterministic:
            abstentions.append(
                AutopilotAbstention(
                    code="capability_not_deterministic",
                    subject=capability_id,
                    message="The declared planner capability has no deterministic scope.",
                )
            )
    for permission in sorted(required_permissions - set(policy.allowed_permissions)):
        abstentions.append(
            AutopilotAbstention(
                code="permission_absent",
                subject=permission,
                message="The creative policy does not grant this required permission.",
            )
        )
    return tuple(abstentions)


def plan_creative_autopilot(
    *,
    manifest: ProjectManifest | Mapping[str, Any],
    request: AutopilotRequest | Mapping[str, Any],
    capabilities: Sequence[PlannerCapability | Mapping[str, Any]],
    policy: AutopilotPolicy | Mapping[str, Any],
) -> AutopilotResult:
    """Coordinate pure planners after explicit capability and policy gates."""

    valid_manifest = _validated(manifest, ProjectManifest)
    valid_request = _validated(request, AutopilotRequest)
    valid_capabilities = _validated_sequence(capabilities, PlannerCapability)
    valid_policy = _validated(policy, AutopilotPolicy)
    required_ids = tuple(sorted(set(AUTOPILOT_REQUIRED_CAPABILITIES) | set(valid_request.required_capability_ids)))
    abstentions = _capability_abstentions(
        required_ids, valid_capabilities, valid_policy, valid_request.required_permissions
    )
    if abstentions:
        return _result(
            manifest=valid_manifest,
            request=valid_request,
            policy=valid_policy,
            capabilities=valid_capabilities,
            capability_ids=required_ids,
            abstentions=abstentions,
        )

    selection = select_assets(
        manifest=valid_manifest,
        intent=valid_request.selection_intent,
        evidence=valid_request.selection_evidence,
    )
    if selection.abstentions:
        selection_abstentions = tuple(
            AutopilotAbstention(
                code="selection_prerequisite_absent",
                subject=item.role,
                message=f"{item.code}: {item.reason}",
            )
            for item in selection.abstentions
        )
        return _result(
            manifest=valid_manifest,
            request=valid_request,
            policy=valid_policy,
            capabilities=valid_capabilities,
            capability_ids=required_ids,
            abstentions=selection_abstentions,
        )
    try:
        plan = plan_composition(
            manifest=valid_manifest,
            selection=selection,
            intent=valid_request.composition_intent,
            layouts=valid_request.layouts,
            graphics=valid_request.graphics,
            audio_tracks=valid_request.audio_tracks,
            caption_plan=valid_request.caption_plan,
            output_variants=valid_request.output_variants,
        )
    except CreativeContractError as exc:
        return _result(
            manifest=valid_manifest,
            request=valid_request,
            policy=valid_policy,
            capabilities=valid_capabilities,
            capability_ids=required_ids,
            abstentions=(
                AutopilotAbstention(
                    code="planner_prerequisite_absent",
                    subject=exc.code,
                    message=str(exc),
                ),
            ),
        )
    preview = build_composition_preview(plan)
    return _result(
        manifest=valid_manifest,
        request=valid_request,
        policy=valid_policy,
        capabilities=valid_capabilities,
        capability_ids=required_ids,
        plan=plan,
        preview=preview,
    )
