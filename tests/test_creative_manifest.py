from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_video.creative import (
    AssetRights,
    BrandConstraints,
    CreativeAsset,
    CreativeContractError,
    QualityFinding,
    RoleCandidate,
    SelectionEvidence,
    SelectionIntent,
    SemanticSpan,
    build_project_manifest,
    select_assets,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _video_asset() -> CreativeAsset:
    return CreativeAsset(
        id="asset:camera_a",
        path="sources/camera-a.mp4",
        sha256=SHA_A,
        media_kind="video",
        rights=AssetRights(
            status="cleared",
            provenance="Recorded and supplied by the user.",
            attribution_required=False,
        ),
        semantic_spans=(
            SemanticSpan(
                id="span:camera_a_intro",
                kind="scene",
                start_seconds=0.0,
                end_seconds=4.0,
                confidence=0.94,
                provenance="semantic_timeline:v1",
                text="Opening remarks",
            ),
        ),
        quality_findings=(
            QualityFinding(
                id="quality:camera_a_exposure",
                kind="exposure",
                severity="advisory",
                summary="Exposure is usable.",
                confidence=0.88,
                evidence=("metric:luma_p50",),
            ),
        ),
        role_candidates=(
            RoleCandidate(
                role="primary_video",
                confidence=0.9,
                rationale="Contains the source-backed opening scene.",
                span_ids=("span:camera_a_intro",),
            ),
        ),
        user_supplied=True,
    )


def _logo_asset() -> CreativeAsset:
    return CreativeAsset(
        id="asset:brand_logo",
        path="brand/logo.png",
        sha256=SHA_B,
        media_kind="image",
        rights=AssetRights(
            status="cleared",
            provenance="User-supplied brand asset.",
            attribution_required=False,
        ),
        role_candidates=(
            RoleCandidate(
                role="logo",
                confidence=1.0,
                rationale="Explicitly supplied as the project logo.",
            ),
        ),
        user_supplied=True,
    )


def test_manifest_binds_assets_and_user_brand_constraints_deterministically() -> None:
    constraints = BrandConstraints(
        logo_asset_ids=("asset:brand_logo",),
        music_asset_ids=(),
        font_asset_ids=(),
        caption_asset_ids=(),
        required_colors=("#123456",),
        required_text=("Kyanite Labs",),
        forbidden_text=("unapproved claim",),
    )

    first = build_project_manifest(
        project_id="project:launch_recap",
        assets=(_video_asset(), _logo_asset()),
        brand_constraints=constraints,
    )
    second = build_project_manifest(
        project_id="project:launch_recap",
        assets=(_logo_asset(), _video_asset()),
        brand_constraints=constraints,
    )

    assert first == second
    assert first.manifest_sha256.startswith("sha256:")
    assert tuple(asset.id for asset in first.assets) == ("asset:brand_logo", "asset:camera_a")
    assert first.assets[1].semantic_spans[0].id == "span:camera_a_intro"
    assert first.assets[1].quality_findings[0].evidence == ("metric:luma_p50",)
    assert first.brand_constraints.logo_asset_ids == ("asset:brand_logo",)


def test_manifest_rejects_brand_references_to_missing_assets() -> None:
    with pytest.raises(ValidationError, match="brand constraint references unknown asset"):
        build_project_manifest(
            project_id="project:launch_recap",
            assets=(_video_asset(),),
            brand_constraints=BrandConstraints(logo_asset_ids=("asset:missing",)),
        )


def test_selection_is_source_backed_and_reports_explicit_confidence() -> None:
    manifest = build_project_manifest(
        project_id="project:launch_recap",
        assets=(_video_asset(), _logo_asset()),
        brand_constraints=BrandConstraints(logo_asset_ids=("asset:brand_logo",)),
    )
    intent = SelectionIntent(
        id="selection:launch_recap",
        query="opening remarks with approved branding",
        required_roles=("primary_video", "logo"),
    )
    evidence = (
        SelectionEvidence(
            id="evidence:camera_intro",
            role="primary_video",
            asset_id="asset:camera_a",
            span_ids=("span:camera_a_intro",),
            confidence=0.92,
            rationale="Semantic retrieval matched the requested opening remarks.",
            source="semantic_index:v1",
        ),
        SelectionEvidence(
            id="evidence:explicit_logo",
            role="logo",
            asset_id="asset:brand_logo",
            confidence=1.0,
            rationale="The brand constraint explicitly identifies this logo.",
            source="project_manifest:v1",
        ),
    )

    plan = select_assets(manifest=manifest, intent=intent, evidence=evidence)

    assert plan.abstentions == ()
    assert tuple(item.role for item in plan.selections) == ("logo", "primary_video")
    primary = next(item for item in plan.selections if item.role == "primary_video")
    assert primary.asset_id == "asset:camera_a"
    assert primary.span_ids == ("span:camera_a_intro",)
    assert primary.confidence == pytest.approx(0.91)
    assert primary.evidence_ids == ("evidence:camera_intro",)
    assert primary.confidence_rationale


def test_selection_abstains_without_source_evidence_and_never_falls_back() -> None:
    manifest = build_project_manifest(
        project_id="project:launch_recap",
        assets=(_video_asset(),),
    )

    plan = select_assets(
        manifest=manifest,
        intent=SelectionIntent(
            id="selection:no_evidence",
            query="pick something",
            required_roles=("primary_video",),
        ),
        evidence=(),
    )

    assert plan.selections == ()
    assert len(plan.abstentions) == 1
    assert plan.abstentions[0].code == "source_evidence_absent"
    assert plan.abstentions[0].role == "primary_video"


def test_public_manifest_and_selection_apis_accept_json_compatible_inputs() -> None:
    manifest = build_project_manifest(
        project_id="project:json_boundary",
        assets=[_video_asset().model_dump(mode="json")],
        brand_constraints={"required_text": ["Approved"]},
    )

    plan = select_assets(
        manifest=manifest.model_dump(mode="json"),
        intent={
            "id": "selection:json_boundary",
            "query": "opening remarks",
            "required_roles": ["primary_video"],
        },
        evidence=[
            {
                "id": "evidence:json_boundary",
                "role": "primary_video",
                "asset_id": "asset:camera_a",
                "span_ids": ["span:camera_a_intro"],
                "confidence": 0.92,
                "rationale": "Declared semantic match.",
                "source": "semantic_index:v1",
            }
        ],
    )

    assert plan.selections[0].asset_id == "asset:camera_a"
    assert plan.model_dump(mode="json")["selection_sha256"].startswith("sha256:")


def test_selection_rejects_a_tampered_manifest_hash() -> None:
    manifest = build_project_manifest(project_id="project:tampered", assets=(_video_asset(),))
    tampered = manifest.model_copy(update={"manifest_sha256": SHA_B})

    with pytest.raises(CreativeContractError, match="manifest_sha256"):
        select_assets(
            manifest=tampered,
            intent=SelectionIntent(
                id="selection:tampered",
                query="opening remarks",
                required_roles=("primary_video",),
            ),
            evidence=(),
        )
