from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_video.creative import (
    ALLOWED_COMPILE_TARGETS,
    AssetRights,
    AttributionEvidence,
    AudioMixTrack,
    AudioObservation,
    BrandConstraints,
    BrandingObservation,
    CaptionPlan,
    CreativeAsset,
    CreativeContractError,
    GraphicElement,
    LayoutSpec,
    OutputArtifact,
    OutputPackageEvidence,
    OutputVariant,
    RoleCandidate,
    SelectionEvidence,
    SelectionIntent,
    SemanticSpan,
    TextObservation,
    TimelineObservation,
    VerificationEvidence,
    bind_composition_approval,
    build_composition_preview,
    build_project_manifest,
    compile_composition_plan,
    plan_composition,
    select_assets,
    verify_composition,
)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _asset(
    asset_id: str,
    path: str,
    media_kind: str,
    role: str,
    hash_character: str,
    span: SemanticSpan | None = None,
) -> CreativeAsset:
    return CreativeAsset(
        id=asset_id,
        path=path,
        sha256=_sha(hash_character),
        media_kind=media_kind,
        rights=AssetRights(
            status="cleared",
            provenance="User supplied and declared rights cleared.",
            attribution_required=False,
        ),
        semantic_spans=(span,) if span else (),
        role_candidates=(
            RoleCandidate(
                role=role,
                confidence=1.0,
                rationale=f"Explicit {role} asset.",
                span_ids=(span.id,) if span else (),
            ),
        ),
        user_supplied=True,
    )


def _manifest_and_selection():
    video_span = SemanticSpan(
        id="span:video_intro",
        kind="scene",
        start_seconds=2.0,
        end_seconds=6.0,
        confidence=0.96,
        provenance="semantic_timeline:v1",
        text="Launch recap opening",
    )
    music_span = SemanticSpan(
        id="span:music_bed",
        kind="audio_event",
        start_seconds=0.0,
        end_seconds=4.0,
        confidence=1.0,
        provenance="user_selection:v1",
    )
    caption_span = SemanticSpan(
        id="span:captions_intro",
        kind="transcript",
        start_seconds=0.0,
        end_seconds=4.0,
        confidence=0.99,
        provenance="user_captions:v1",
        text="Launch recap opening",
    )
    assets = (
        _asset("asset:video", "sources/video.mp4", "video", "primary_video", "1", video_span),
        _asset("asset:music", "sources/music.wav", "audio", "music", "2", music_span),
        _asset("asset:logo", "brand/logo.png", "image", "logo", "3"),
        _asset("asset:font", "brand/font.woff2", "font", "font", "4"),
        _asset("asset:captions", "captions/approved.srt", "captions", "captions", "5", caption_span),
    )
    manifest = build_project_manifest(
        project_id="project:composition",
        assets=assets,
        brand_constraints=BrandConstraints(
            logo_asset_ids=("asset:logo",),
            music_asset_ids=("asset:music",),
            font_asset_ids=("asset:font",),
            caption_asset_ids=("asset:captions",),
            required_colors=("#123456",),
            required_text=("Kyanite Labs",),
            forbidden_text=("guaranteed",),
        ),
    )
    evidence = tuple(
        SelectionEvidence(
            id=f"evidence:{role}",
            role=role,
            asset_id=asset_id,
            span_ids=(span_id,) if span_id else (),
            confidence=1.0,
            rationale=f"Manifest-backed {role} evidence.",
            source="project_manifest:v1",
        )
        for role, asset_id, span_id in (
            ("primary_video", "asset:video", "span:video_intro"),
            ("music", "asset:music", "span:music_bed"),
            ("logo", "asset:logo", None),
            ("font", "asset:font", None),
            ("captions", "asset:captions", "span:captions_intro"),
        )
    )
    selection = select_assets(
        manifest=manifest,
        intent=SelectionIntent(
            id="selection:composition",
            query="four second launch recap",
            required_roles=("primary_video", "music", "logo", "font", "captions"),
        ),
        evidence=evidence,
    )
    return manifest, selection


def _plan(*, include_audio: bool = True, compile_target: str = "workflow.v1"):
    manifest, selection = _manifest_and_selection()
    plan = plan_composition(
        manifest=manifest.model_dump(mode="json"),
        selection=selection.model_dump(mode="json"),
        intent={
            "id": "intent:launch_recap",
            "summary": "Make a four second launch recap.",
            "target_duration_seconds": 4.0,
            "compile_target": compile_target,
        },
        layouts=[
            LayoutSpec(
                id="layout:full_frame",
                kind="full_frame",
                role_bindings=("primary_video",),
            ).model_dump(mode="json")
        ],
        graphics=[
            GraphicElement(
                id="graphic:logo",
                kind="logo",
                asset_id="asset:logo",
                start_seconds=0.0,
                end_seconds=4.0,
            ).model_dump(mode="json"),
            GraphicElement(
                id="graphic:title",
                kind="text",
                text="Kyanite Labs",
                font_asset_id="asset:font",
                color="#123456",
                start_seconds=0.0,
                end_seconds=2.0,
            ).model_dump(mode="json"),
        ],
        audio_tracks=[
            AudioMixTrack(
                id="audio:music",
                asset_id="asset:music",
                span_ids=("span:music_bed",),
                output_start_seconds=0.0,
                output_end_seconds=4.0,
                gain_db=-12.0,
                target_lufs=-16.0,
                max_peak_dbfs=-1.0,
            ).model_dump(mode="json")
        ]
        if include_audio
        else [],
        caption_plan=(
            CaptionPlan(
                id="caption:main",
                asset_id="asset:captions",
                mode="editable_sidecar",
                font_asset_id="asset:font",
                color="#123456",
            ).model_dump(mode="json")
            if include_audio
            else None
        ),
        output_variants=[
            OutputVariant(id="variant:vertical", width=1080, height=1920, container="mp4"),
            OutputVariant(id="variant:square", width=1080, height=1080, container="mp4"),
        ],
    )
    return manifest, plan


def test_composition_plan_maps_intent_to_all_declared_surfaces_deterministically() -> None:
    manifest, first = _plan()
    _, second = _plan()

    assert first == second
    assert first.manifest_sha256 == manifest.manifest_sha256
    assert first.plan_sha256.startswith("sha256:")
    assert tuple(binding.role for binding in first.source_bindings) == (
        "captions",
        "font",
        "logo",
        "music",
        "primary_video",
    )
    assert len(first.timeline) == 1
    assert first.timeline[0].source_start_seconds == 2.0
    assert first.timeline[0].source_end_seconds == 6.0
    assert first.timeline[0].output_start_seconds == 0.0
    assert first.timeline[0].output_end_seconds == 4.0
    assert first.layouts[0].id == "layout:full_frame"
    assert tuple(item.id for item in first.graphics) == ("graphic:logo", "graphic:title")
    assert first.audio_tracks[0].asset_id == "asset:music"
    assert first.caption_plan and first.caption_plan.asset_id == "asset:captions"
    assert tuple(item.id for item in first.output_variants) == ("variant:square", "variant:vertical")
    assert first.verifier_ids == (
        "source_attribution",
        "timeline_coverage",
        "audio_mix",
        "text_layout",
        "branding",
        "variant_contracts",
        "package_integrity",
    )


def test_storyboard_timeline_preview_and_approval_bind_exact_plan() -> None:
    _, plan = _plan()

    first = build_composition_preview(plan.model_dump(mode="json"))
    second = build_composition_preview(plan)
    approval = bind_composition_approval(first.model_dump(mode="json"))

    assert first == second
    assert first.plan_sha256 == plan.plan_sha256
    assert first.storyboard[0].segment_id == plan.timeline[0].id
    assert first.timeline[0].selected_span_ids == plan.timeline[0].selected_span_ids
    assert first.preview_sha256.startswith("sha256:")
    assert approval.plan_sha256 == plan.plan_sha256
    assert approval.preview_sha256 == first.preview_sha256
    assert approval.approval_sha256.startswith("sha256:")


def test_compiler_is_declarative_allowlisted_and_rejects_unsupported_features() -> None:
    manifest, full_plan = _plan()

    assert ALLOWED_COMPILE_TARGETS == ("compositor.v1", "workflow.v1")
    with pytest.raises(CreativeContractError, match="does not support planned audio or captions"):
        compile_composition_plan(manifest=manifest, plan=full_plan)

    _, graphics_only = _plan(include_audio=False)
    compiled = compile_composition_plan(
        manifest=manifest.model_dump(mode="json"),
        plan=graphics_only.model_dump(mode="json"),
    )

    assert compiled.target_id == "workflow.v1"
    assert compiled.renders_nothing is True
    assert compiled.operations
    assert {operation.op for operation in compiled.operations} <= {
        "trim",
        "resize",
        "merge",
        "add_text",
        "composite_layers",
    }
    assert all("filter" not in operation.parameters for operation in compiled.operations)

    _, invalid_target = _plan(include_audio=False, compile_target="shell.v1")
    with pytest.raises(CreativeContractError, match="compile target is not allowlisted"):
        compile_composition_plan(manifest=manifest, plan=invalid_target)


def _verification_evidence(plan, approval) -> VerificationEvidence:
    attributions = tuple(
        AttributionEvidence(asset_id=binding.asset_id, span_id=span_id)
        for binding in plan.source_bindings
        for span_id in (binding.span_ids or (None,))
    )
    timeline = tuple(
        TimelineObservation(
            segment_id=segment.id,
            output_start_seconds=segment.output_start_seconds,
            output_end_seconds=segment.output_end_seconds,
            selected_span_ids=segment.selected_span_ids,
        )
        for segment in plan.timeline
    )
    artifacts = tuple(
        OutputArtifact(
            variant_id=variant.id,
            path=f"package/{variant.id.split(':')[1]}.mp4",
            sha256=_sha(str(index + 6)),
            size_bytes=1024,
            width=variant.width,
            height=variant.height,
            container=variant.container,
        )
        for index, variant in enumerate(plan.output_variants)
    )
    return VerificationEvidence(
        attributions=attributions,
        timeline=timeline,
        audio=(AudioObservation(track_id="audio:music", integrated_lufs=-16.0, peak_dbfs=-1.2),),
        text=(
            TextObservation(
                element_id="graphic:title",
                rendered_text="Kyanite Labs",
                inside_safe_area=True,
                readable=True,
            ),
            TextObservation(
                element_id="caption:main",
                rendered_text="Launch recap opening",
                inside_safe_area=True,
                readable=True,
            ),
        ),
        branding=BrandingObservation(
            logo_asset_ids=("asset:logo",),
            font_asset_ids=("asset:font",),
            colors=("#123456",),
            rendered_text=("Kyanite Labs", "Launch recap opening"),
        ),
        package=OutputPackageEvidence(
            plan_sha256=plan.plan_sha256,
            approval_sha256=approval.approval_sha256,
            artifacts=artifacts,
        ),
    )


def test_verifier_checks_attribution_timeline_audio_text_brand_variants_and_package() -> None:
    _, plan = _plan()
    preview = build_composition_preview(plan)
    approval = bind_composition_approval(preview)
    evidence = _verification_evidence(plan, approval)

    report = verify_composition(
        plan=plan.model_dump(mode="json"),
        approval=approval.model_dump(mode="json"),
        evidence=evidence.model_dump(mode="json"),
    )

    assert report.passed is True
    assert tuple(check.id for check in report.checks) == plan.verifier_ids
    assert all(check.passed for check in report.checks)
    assert report.report_sha256.startswith("sha256:")

    incomplete = evidence.model_copy(update={"attributions": evidence.attributions[1:]})
    failed = verify_composition(plan=plan, approval=approval, evidence=incomplete)

    assert failed.passed is False
    attribution = next(check for check in failed.checks if check.id == "source_attribution")
    assert attribution.passed is False
    assert attribution.details["missing"]


def test_composition_rejects_unknown_audio_spans_and_mutated_verifier_sets() -> None:
    manifest, selection = _manifest_and_selection()
    with pytest.raises(CreativeContractError, match="unknown semantic span"):
        plan_composition(
            manifest=manifest,
            selection=selection,
            intent={
                "id": "intent:invalid_audio",
                "summary": "Invalid audio reference.",
                "target_duration_seconds": 4.0,
                "compile_target": "workflow.v1",
            },
            layouts=[{"id": "layout:full", "kind": "full_frame", "role_bindings": ["primary_video"]}],
            graphics=[
                {
                    "id": "graphic:title",
                    "kind": "text",
                    "text": "Kyanite Labs",
                    "font_asset_id": "asset:font",
                    "color": "#123456",
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                }
            ],
            audio_tracks=[
                {
                    "id": "audio:invalid",
                    "asset_id": "asset:music",
                    "span_ids": ["span:missing"],
                    "output_start_seconds": 0.0,
                    "output_end_seconds": 4.0,
                    "gain_db": -12.0,
                    "target_lufs": -16.0,
                    "max_peak_dbfs": -1.0,
                }
            ],
            output_variants=[{"id": "variant:main", "width": 1080, "height": 1080, "container": "mp4"}],
        )

    _, plan = _plan()
    with pytest.raises(ValidationError, match="verifier_ids"):
        plan.__class__.model_validate({**plan.model_dump(mode="json"), "verifier_ids": ["package_integrity"]})
