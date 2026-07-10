"""Shared JSON-compatible adapters for post-rescue planning surfaces."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import MCPVideoError

JsonObject = dict[str, Any]


def _invalid(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_post_rescue_request")


def _request(value: Mapping[str, Any]) -> JsonObject:
    if not isinstance(value, Mapping):
        raise _invalid("Post-rescue requests must be JSON objects.")
    return dict(value)


def _payload(request: JsonObject) -> JsonObject:
    payload = request.get("payload")
    if payload is None:
        return {key: value for key, value in request.items() if key != "operation"}
    if not isinstance(payload, Mapping):
        raise _invalid("The request payload must be a JSON object.")
    return dict(payload)


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_dump(item) for item in value]
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


def _dispatch(request: JsonObject, operations: Mapping[str, Callable[..., Any]], default: str) -> Any:
    operation = str(request.get("operation", default))
    try:
        function = operations[operation]
    except KeyError as exc:
        allowed = ", ".join(sorted(operations))
        raise _invalid(f"Unsupported operation '{operation}'. Expected one of: {allowed}.") from exc
    return function(**_payload(request))


def load_post_rescue_request(path: str) -> JsonObject:
    """Load one bounded JSON request artifact for the CLI."""

    resolved = Path(path).expanduser().resolve()
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise _invalid("Could not read the post-rescue request artifact.") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise _invalid("Post-rescue request exceeds the 4 MiB limit.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid(f"Post-rescue request is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise _invalid("Post-rescue request must contain a JSON object.")
    return value


def call_post_rescue(function: Callable[[Mapping[str, Any]], JsonObject], request: Mapping[str, Any]) -> JsonObject:
    """Run a public adapter and normalize schema failures to MCP Video errors."""

    try:
        return function(request)
    except MCPVideoError:
        raise
    except (ValidationError, TypeError, ValueError) as exc:
        raise _invalid("Post-rescue request did not match the required contract.") from exc


def semantic_timeline(request: Mapping[str, Any]) -> JsonObject:
    from .semantic import build_semantic_timeline

    return _dump(build_semantic_timeline(**_request(request)))


def semantic_query(request: Mapping[str, Any]) -> JsonObject:
    from .semantic import query_local_index

    values = _request(request)
    try:
        artifact = values.pop("artifact")
    except KeyError as exc:
        raise _invalid("Semantic query requires an artifact.") from exc
    return _dump(query_local_index(artifact, **values))


def timeline_edit_plan(request: Mapping[str, Any]) -> JsonObject:
    from .semantic import build_edl, generate_ordinary_cleanup_edits
    from .semantic.edl import approve_edl, plan_timeline_diff, verify_timeline_diff
    from .semantic.models import SemanticTimeline

    values = _request(request)
    try:
        timeline = SemanticTimeline.model_validate(values.pop("timeline"))
    except KeyError as exc:
        raise _invalid("Timeline edit planning requires a semantic timeline.") from exc
    selected = values.pop("selected_edit_ids", None)
    if "behavior" in values:
        behavior = values.pop("behavior")
        options = values.pop("options", None)
        if values:
            raise _invalid(f"Unexpected cleanup request fields: {', '.join(sorted(values))}.")
        edl = generate_ordinary_cleanup_edits(timeline, behavior=behavior, options=options)
    else:
        edits = values.pop("edits", None)
        if edits is None or values:
            raise _invalid("Timeline edit planning requires either behavior/options or edits.")
        edl = build_edl(timeline, edits=edits)
    result: JsonObject = {"edl": _dump(edl)}
    if selected is not None:
        approval = approve_edl(edl, selected_edit_ids=selected)
        diff = plan_timeline_diff(timeline, edl, approval)
        result.update(
            approval=_dump(approval),
            diff=_dump(diff),
            verification=_dump(verify_timeline_diff(timeline, edl, approval, diff)),
        )
    return result


def visual_transform_plan(request: Mapping[str, Any]) -> JsonObject:
    from .visual_intelligence import (
        plan_stabilization,
        plan_subject_aware_reframe,
        plan_visual_analysis,
    )

    return _dump(
        _dispatch(
            _request(request),
            {
                "analysis": plan_visual_analysis,
                "reframe": plan_subject_aware_reframe,
                "stabilization": plan_stabilization,
            },
            "analysis",
        )
    )


def restoration_plan(request: Mapping[str, Any]) -> JsonObject:
    from .restorative import evaluate_restoration, plan_restoration

    values = _request(request)
    operation = str(values.pop("operation", "plan"))
    if operation == "plan":
        return _dump(plan_restoration(_payload(values)))
    if operation == "evaluate":
        return _dump(evaluate_restoration(**_payload(values)))
    raise _invalid("Restoration operation must be 'plan' or 'evaluate'.")


def composition_plan(request: Mapping[str, Any]) -> JsonObject:
    from .creative import (
        bind_composition_approval,
        build_composition_preview,
        build_project_manifest,
        compile_composition_plan,
        plan_composition,
        select_assets,
        verify_composition,
    )

    return _dump(
        _dispatch(
            _request(request),
            {
                "manifest": build_project_manifest,
                "select": select_assets,
                "plan": plan_composition,
                "preview": build_composition_preview,
                "approve": bind_composition_approval,
                "compile": compile_composition_plan,
                "verify": verify_composition,
            },
            "plan",
        )
    )


def creative_autopilot_plan(request: Mapping[str, Any]) -> JsonObject:
    from .creative import plan_creative_autopilot

    return _dump(plan_creative_autopilot(**_request(request)))


def remote_egress_plan(request: Mapping[str, Any]) -> JsonObject:
    from .remote import (
        approve_egress,
        create_fake_remote_receipt,
        map_fake_remote_job,
        plan_delivery,
        plan_egress,
        plan_hosting,
        validate_egress_approval,
        verify_local_promotion,
    )

    return _dump(
        _dispatch(
            _request(request),
            {
                "plan": plan_egress,
                "approve": approve_egress,
                "validate_approval": validate_egress_approval,
                "map_fake_job": map_fake_remote_job,
                "delivery": plan_delivery,
                "hosting": plan_hosting,
                "fake_receipt": create_fake_remote_receipt,
                "verify_local_promotion": verify_local_promotion,
            },
            "plan",
        )
    )
