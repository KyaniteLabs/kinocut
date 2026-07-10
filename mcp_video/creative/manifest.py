"""Pure project-manifest construction and source-backed asset selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import CreativeContractError
from .models import (
    AssetSelection,
    BrandConstraints,
    CreativeAsset,
    ProjectManifest,
    SelectionAbstention,
    SelectionEvidence,
    SelectionIntent,
    SelectionPlan,
    canonical_digest,
)

_ZERO_SHA256 = "sha256:" + "0" * 64


def build_project_manifest(
    *,
    project_id: str,
    assets: Sequence[CreativeAsset | Mapping[str, Any]],
    brand_constraints: BrandConstraints | Mapping[str, Any] | None = None,
) -> ProjectManifest:
    """Bind caller-supplied asset evidence without inspecting or sourcing files."""

    validated_assets = tuple(
        asset if isinstance(asset, CreativeAsset) else CreativeAsset.model_validate(asset) for asset in assets
    )
    validated_constraints = (
        BrandConstraints()
        if brand_constraints is None
        else brand_constraints
        if isinstance(brand_constraints, BrandConstraints)
        else BrandConstraints.model_validate(brand_constraints)
    )
    draft = ProjectManifest(
        project_id=project_id,
        assets=tuple(sorted(validated_assets, key=lambda asset: asset.id)),
        brand_constraints=validated_constraints,
        manifest_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"manifest_sha256": canonical_digest(draft, exclude={"manifest_sha256"})})


def _validate_evidence(manifest: ProjectManifest, evidence: tuple[SelectionEvidence, ...]) -> None:
    assets = {asset.id: asset for asset in manifest.assets}
    evidence_ids = tuple(item.id for item in evidence)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise CreativeContractError("duplicate_selection_evidence", "Selection evidence ids must be unique.")
    for item in evidence:
        asset = assets.get(item.asset_id)
        if asset is None:
            raise CreativeContractError(
                "unknown_selection_asset", f"Selection evidence {item.id} references an unknown asset."
            )
        known_spans = {span.id for span in asset.semantic_spans}
        if not set(item.span_ids).issubset(known_spans):
            raise CreativeContractError(
                "unknown_selection_span", f"Selection evidence {item.id} references an unknown semantic span."
            )


def _select_role(
    manifest: ProjectManifest,
    role: str,
    evidence: tuple[SelectionEvidence, ...],
    minimum_confidence: float,
) -> tuple[AssetSelection | None, SelectionAbstention | None]:
    candidates: list[tuple[float, str, SelectionEvidence, str]] = []
    matching_evidence = tuple(item for item in evidence if item.role == role)
    if not matching_evidence:
        return None, SelectionAbstention(
            role=role,
            code="source_evidence_absent",
            reason="No declared source evidence supports this required role.",
        )

    for asset in manifest.assets:
        for role_candidate in asset.role_candidates:
            if role_candidate.role != role:
                continue
            for item in matching_evidence:
                if item.asset_id != asset.id:
                    continue
                if role_candidate.span_ids and not set(item.span_ids).issubset(set(role_candidate.span_ids)):
                    continue
                score = round((role_candidate.confidence + item.confidence) / 2.0, 6)
                candidates.append((score, asset.id, item, role_candidate.rationale))

    if not candidates:
        return None, SelectionAbstention(
            role=role,
            code="source_evidence_absent",
            reason="Declared evidence does not match a manifest role candidate.",
        )
    candidates.sort(key=lambda item: (-item[0], item[1], item[2].id))
    score, asset_id, selected_evidence, role_rationale = candidates[0]
    asset = next(item for item in manifest.assets if item.id == asset_id)
    if asset.rights.status != "cleared":
        return None, SelectionAbstention(
            role=role,
            code="rights_not_cleared",
            reason=f"Best source-backed candidate {asset_id} does not have cleared rights.",
        )
    if score < minimum_confidence:
        return None, SelectionAbstention(
            role=role,
            code="confidence_below_threshold",
            reason=f"Best source-backed confidence {score:.3f} is below {minimum_confidence:.3f}.",
        )
    return (
        AssetSelection(
            role=role,
            asset_id=asset_id,
            span_ids=selected_evidence.span_ids,
            confidence=score,
            confidence_rationale=(
                f"Manifest role confidence and {selected_evidence.source} evidence agree: "
                f"{role_rationale} {selected_evidence.rationale}"
            ),
            evidence_ids=(selected_evidence.id,),
        ),
        None,
    )


def select_assets(
    *,
    manifest: ProjectManifest | Mapping[str, Any],
    intent: SelectionIntent | Mapping[str, Any],
    evidence: Sequence[SelectionEvidence | Mapping[str, Any]],
    minimum_confidence: float = 0.5,
) -> SelectionPlan:
    """Select only evidence-backed, rights-cleared candidates or explicitly abstain."""

    if not 0.0 <= minimum_confidence <= 1.0:
        raise CreativeContractError("invalid_confidence_threshold", "minimum_confidence must be between 0 and 1.")
    validated_manifest = manifest if isinstance(manifest, ProjectManifest) else ProjectManifest.model_validate(manifest)
    validated_intent = intent if isinstance(intent, SelectionIntent) else SelectionIntent.model_validate(intent)
    validated_evidence = tuple(
        item if isinstance(item, SelectionEvidence) else SelectionEvidence.model_validate(item) for item in evidence
    )
    if validated_manifest.manifest_sha256 != canonical_digest(validated_manifest, exclude={"manifest_sha256"}):
        raise CreativeContractError(
            "manifest_hash_mismatch", "manifest_sha256 does not match the canonical contract payload."
        )
    _validate_evidence(validated_manifest, validated_evidence)
    selections: list[AssetSelection] = []
    abstentions: list[SelectionAbstention] = []
    for role in sorted(validated_intent.required_roles):
        selection, abstention = _select_role(validated_manifest, role, validated_evidence, minimum_confidence)
        if selection is not None:
            selections.append(selection)
        if abstention is not None:
            abstentions.append(abstention)
    draft = SelectionPlan(
        manifest_sha256=validated_manifest.manifest_sha256,
        intent=validated_intent,
        selections=tuple(selections),
        abstentions=tuple(abstentions),
        selection_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"selection_sha256": canonical_digest(draft, exclude={"selection_sha256"})})
