"""Declarative, allowlisted composition compilation with no execution side effects."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .composition import _require_digest, _validated
from .composition_models import CompileOperation, CompiledComposition, CompositionPlan
from .errors import CreativeContractError
from .models import ProjectManifest, canonical_digest

_ZERO_SHA256 = "sha256:" + "0" * 64
ALLOWED_COMPILE_TARGETS = ("compositor.v1", "workflow.v1")
COMPILE_TARGET_OPERATIONS = MappingProxyType(
    {
        "compositor.v1": frozenset({"trim", "resize", "merge", "add_text", "composite_layers"}),
        "workflow.v1": frozenset({"trim", "resize", "merge", "add_text", "composite_layers"}),
    }
)


def compile_composition_plan(
    *,
    manifest: ProjectManifest | Mapping[str, Any],
    plan: CompositionPlan | Mapping[str, Any],
) -> CompiledComposition:
    """Compile to a reviewed operation vocabulary; never invoke those operations."""

    valid_manifest = _validated(manifest, ProjectManifest)
    valid_plan = _validated(plan, CompositionPlan)
    if valid_plan.compile_target not in ALLOWED_COMPILE_TARGETS:
        raise CreativeContractError("compile_target_not_allowlisted", "Composition compile target is not allowlisted.")
    _require_digest(valid_manifest, "manifest_sha256", "manifest_hash_mismatch")
    _require_digest(valid_plan, "plan_sha256", "composition_plan_hash_mismatch")
    if valid_plan.manifest_sha256 != valid_manifest.manifest_sha256:
        raise CreativeContractError("compile_manifest_mismatch", "Composition and manifest hashes do not match.")
    if valid_plan.audio_tracks or valid_plan.caption_plan is not None:
        raise CreativeContractError(
            "compile_feature_unsupported",
            f"{valid_plan.compile_target} does not support planned audio or captions; no fallback is permitted.",
        )
    asset_paths = {asset.id: asset.path for asset in valid_manifest.assets}
    operations: list[CompileOperation] = []
    for segment in valid_plan.timeline:
        operations.append(
            CompileOperation(
                id=f"operation:trim_{len(operations) + 1:03d}",
                op="trim",
                parameters={
                    "src": asset_paths[segment.asset_id],
                    "start_seconds": segment.source_start_seconds,
                    "end_seconds": segment.source_end_seconds,
                    "segment_id": segment.id,
                },
            )
        )
    for graphic in valid_plan.graphics:
        op = "add_text" if graphic.kind == "text" else "composite_layers"
        parameters: dict[str, Any] = {
            "graphic_id": graphic.id,
            "start_seconds": graphic.start_seconds,
            "end_seconds": graphic.end_seconds,
        }
        if graphic.kind == "text":
            parameters.update({"text": graphic.text, "color": graphic.color, "font_asset_id": graphic.font_asset_id})
        else:
            parameters["asset_path"] = asset_paths[graphic.asset_id or ""]
        operations.append(
            CompileOperation(id=f"operation:{op}_{len(operations) + 1:03d}", op=op, parameters=parameters)
        )
    for variant in valid_plan.output_variants:
        operations.append(
            CompileOperation(
                id=f"operation:resize_{len(operations) + 1:03d}",
                op="resize",
                parameters={"variant_id": variant.id, "width": variant.width, "height": variant.height},
            )
        )
    allowed = COMPILE_TARGET_OPERATIONS[valid_plan.compile_target]
    if any(operation.op not in allowed for operation in operations):
        raise CreativeContractError(
            "compile_operation_not_allowlisted", "Compiler produced a non-allowlisted operation."
        )
    draft = CompiledComposition(
        plan_sha256=valid_plan.plan_sha256,
        target_id=valid_plan.compile_target,
        operations=tuple(operations),
        compile_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"compile_sha256": canonical_digest(draft, exclude={"compile_sha256"})})
