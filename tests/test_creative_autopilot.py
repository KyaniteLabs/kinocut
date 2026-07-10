from __future__ import annotations

from mcp_video.creative import (
    AUTOPILOT_REQUIRED_CAPABILITIES,
    AutopilotPolicy,
    PlannerCapability,
    plan_creative_autopilot,
)
from tests.test_creative_composition import _plan


def _capabilities() -> list[dict[str, object]]:
    return [
        PlannerCapability(
            id=capability_id,
            version="1",
            proven=True,
            available=True,
            deterministic=True,
            determinism_scope="Pure local planning over versioned JSON contracts.",
            required_permissions=("timeline",) if capability_id == "planner:composition" else (),
        ).model_dump(mode="json")
        for capability_id in AUTOPILOT_REQUIRED_CAPABILITIES
    ]


def _request() -> tuple[dict[str, object], dict[str, object]]:
    manifest, composition = _plan()
    selection_evidence = [
        {
            "id": binding.evidence_ids[0],
            "role": binding.role,
            "asset_id": binding.asset_id,
            "span_ids": list(binding.span_ids),
            "confidence": binding.confidence,
            "rationale": "Replayed declared source evidence for deterministic coordination.",
            "source": "project_manifest:v1",
        }
        for binding in composition.source_bindings
    ]
    request = {
        "id": "autopilot:launch_recap",
        "required_capability_ids": [],
        "required_permissions": ["timeline"],
        "selection_intent": {
            "id": "selection:autopilot",
            "query": "four second launch recap",
            "required_roles": [binding.role for binding in composition.source_bindings],
        },
        "selection_evidence": selection_evidence,
        "composition_intent": composition.intent.model_dump(mode="json"),
        "layouts": [item.model_dump(mode="json") for item in composition.layouts],
        "graphics": [item.model_dump(mode="json") for item in composition.graphics],
        "audio_tracks": [item.model_dump(mode="json") for item in composition.audio_tracks],
        "caption_plan": composition.caption_plan.model_dump(mode="json") if composition.caption_plan else None,
        "output_variants": [item.model_dump(mode="json") for item in composition.output_variants],
    }
    return manifest.model_dump(mode="json"), request


def test_autopilot_coordinates_only_declared_proven_planners_and_emits_plan_preview() -> None:
    manifest, request = _request()
    policy = AutopilotPolicy(
        id="policy:local_creative_autopilot",
        version=1,
        allowed_permissions=("timeline", "crop"),
    )

    first = plan_creative_autopilot(
        manifest=manifest,
        request=request,
        capabilities=_capabilities(),
        policy=policy.model_dump(mode="json"),
    )
    second = plan_creative_autopilot(
        manifest=manifest,
        request=request,
        capabilities=_capabilities(),
        policy=policy,
    )

    assert first == second
    assert first.status == "planned"
    assert first.abstentions == ()
    assert first.plan is not None
    assert first.preview is not None
    assert first.preview.plan_sha256 == first.plan.plan_sha256
    assert first.capability_ids == AUTOPILOT_REQUIRED_CAPABILITIES
    assert first.manifest_sha256 == manifest["manifest_sha256"]
    assert first.request_sha256.startswith("sha256:")
    assert first.policy_sha256.startswith("sha256:")
    assert first.capability_bindings == tuple(f"{item['id']}@{item['version']}" for item in _capabilities())
    assert first.autopilot_sha256.startswith("sha256:")


def test_autopilot_abstains_when_a_prerequisite_capability_is_missing() -> None:
    manifest, request = _request()

    result = plan_creative_autopilot(
        manifest=manifest,
        request=request,
        capabilities=_capabilities()[:-1],
        policy={
            "id": "policy:local_creative_autopilot",
            "version": 1,
            "allowed_permissions": ["timeline", "crop"],
        },
    )

    assert result.status == "abstained"
    assert result.plan is None
    assert result.preview is None
    assert result.abstentions[0].code == "capability_missing"
    assert result.abstentions[0].subject == AUTOPILOT_REQUIRED_CAPABILITIES[-1]


def test_autopilot_abstains_for_unproven_or_policy_forbidden_work_without_fallback() -> None:
    manifest, request = _request()
    request["required_capability_ids"] = ["planner:restoration"]
    request["required_permissions"] = ["timeline", "synthesis", "network", "asset_sourcing"]
    capabilities = _capabilities()
    capabilities.append(
        PlannerCapability(
            id="planner:restoration",
            version="experimental",
            proven=False,
            available=True,
            deterministic=False,
            determinism_scope="Not established.",
            required_permissions=("synthesis",),
        ).model_dump(mode="json")
    )

    result = plan_creative_autopilot(
        manifest=manifest,
        request=request,
        capabilities=capabilities,
        policy={
            "id": "policy:local_creative_autopilot",
            "version": 1,
            "allowed_permissions": ["timeline"],
        },
    )

    assert result.status == "abstained"
    assert result.plan is None
    assert result.preview is None
    assert {item.code for item in result.abstentions} == {
        "capability_not_proven",
        "capability_not_deterministic",
        "permission_absent",
    }
    assert {item.subject for item in result.abstentions if item.code == "permission_absent"} == {
        "asset_sourcing",
        "network",
        "synthesis",
    }


def test_autopilot_abstains_when_selection_has_no_source_evidence() -> None:
    manifest, request = _request()
    request["selection_evidence"] = []

    result = plan_creative_autopilot(
        manifest=manifest,
        request=request,
        capabilities=_capabilities(),
        policy={
            "id": "policy:local_creative_autopilot",
            "version": 1,
            "allowed_permissions": ["timeline", "crop"],
        },
    )

    assert result.status == "abstained"
    assert result.plan is None
    assert result.preview is None
    assert all(item.code == "selection_prerequisite_absent" for item in result.abstentions)
