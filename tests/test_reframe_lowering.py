"""Tests for :mod:`kinocut.product.reframe_lowering`.

Covers the reframe compile-down seam: only allowlisted ``OP_ADAPTERS`` ops
(``trim``, ``crop``, ``resize``, ``merge``), strict ``crop`` → ``resize`` →
``merge`` ordering, output dimensions matching ``CropVariantPlan.output_width``
/ ``output_height``, deterministic lowering, the explicit PARTIAL review
warning for low-confidence / abstained variants, and the safe static
composition fallback that never silently crops the subject out.

All tests use small deterministic strict-model fixtures built from
:mod:`kinocut.visual_intelligence.models`; no media is rendered and no engine
function is invoked.
"""

from __future__ import annotations

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product.reframe_lowering import (
    REFRAME_ALLOWLISTED_OPS,
    LoweredClipPlan,
    compile_lowered_job,
    lower_reframe_to_dag,
    lower_variant_to_dag,
    parse_lowered_spec,
)
from kinocut.render_dag import compile_dag_to_spec, dag_identity
from kinocut.visual_intelligence.models import (
    CropBudget,
    CropTrackSample,
    CropVariantPlan,
    NormalizedBox,
    ReframePlan,
    SourceVideo,
    canonical_sha256,
)
from kinocut.workflow.ops import OP_ADAPTERS


# --- helpers -----------------------------------------------------------------


def _source_video(width: int = 1920, height: int = 1080) -> SourceVideo:
    """Return a deterministic source video for fixtures."""

    return SourceVideo(
        sha256="sha256:" + "a" * 64,
        width=width,
        height=height,
        duration_seconds=120.0,
    )


def _track_sample(
    *,
    timestamp: float,
    box: tuple[float, float, float, float],
    source_w: int = 960,
    source_h: int = 540,
    subject_coverage: float = 0.9,
) -> CropTrackSample:
    """Return a single ``CropTrackSample`` with the given normalized box."""

    x, y, w, h = box
    return CropTrackSample(
        timestamp_seconds=timestamp,
        crop_box=NormalizedBox(x=x, y=y, width=w, height=h),
        subject_coverage=subject_coverage,
        safe_region_coverage=1.0,
        source_width=source_w,
        source_height=source_h,
    )


def _variant(
    *,
    target_id: str = "yt_1080x1920",
    status: str = "ready",
    abstention_reasons: tuple[str, ...] = (),
    output_width: int = 1080,
    output_height: int = 1920,
    samples: tuple[CropTrackSample, ...] = (),
) -> CropVariantPlan:
    """Return a deterministic ``CropVariantPlan``."""

    return CropVariantPlan(
        target_id=target_id,
        status=status,  # type: ignore[arg-type]
        abstention_reasons=abstention_reasons,
        output_width=output_width,
        output_height=output_height,
        source_crop_fraction=0.5,
        maximum_subject_loss=0.1,
        crop_track=samples,
        previews=(),
    )


def _reframe_plan(variants: tuple[CropVariantPlan, ...]) -> ReframePlan:
    """Return a deterministic :class:`ReframePlan` for the given variants."""

    proto = ReframePlan.model_construct(
        analysis_sha256="sha256:" + "a" * 64,
        source=_source_video(),
        primary_subject_id="s1",
        crop_budget=CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.5),
        min_tracking_confidence=0.7,
        max_center_step=0.1,
        variants=variants,
        plan_sha256="sha256:" + "0" * 64,
    )
    digest = canonical_sha256(proto, exclude={"plan_sha256"})
    return ReframePlan.model_validate({**proto.model_dump(), "plan_sha256": digest})


def _ready_samples(n: int = 2) -> tuple[CropTrackSample, ...]:
    """Return ``n`` deterministic ready-variant crop samples."""

    if n == 1:
        return (
            _track_sample(
                timestamp=0.0,
                box=(0.2, 0.2, 0.4, 0.4),
            ),
        )
    return (
        _track_sample(timestamp=0.0, box=(0.2, 0.2, 0.4, 0.4)),
        _track_sample(timestamp=5.0, box=(0.1, 0.1, 0.5, 0.5)),
    )


# --- allowlist ---------------------------------------------------------------


def test_reframe_allowlisted_ops_are_allowlisted_in_op_adapters() -> None:
    """Every op the lowerer can emit is bound in ``OP_ADAPTERS``."""

    for op in REFRAME_ALLOWLISTED_OPS:
        assert op in OP_ADAPTERS
    assert set(REFRAME_ALLOWLISTED_OPS) == {"trim", "crop", "resize", "merge"}


def test_lowered_ready_dag_uses_only_allowlisted_ops() -> None:
    """A ready variant's lowered DAG emits ONLY allowlisted op names."""

    variant = _variant(samples=_ready_samples())
    job = lower_variant_to_dag(variant, source_video=_source_video())
    emitted = {node.kind for node in job.dag.nodes}
    assert emitted <= set(REFRAME_ALLOWLISTED_OPS)
    assert emitted == {"crop", "resize", "merge"}  # trim omitted (no isolate)


def test_lowered_static_fallback_dag_uses_only_allowlisted_ops() -> None:
    """The static fallback DAG emits ONLY allowlisted op names."""

    variant = _variant(
        status="abstained",
        abstention_reasons=("tracking_loss",),
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    emitted = {node.kind for node in job.dag.nodes}
    assert emitted <= set(REFRAME_ALLOWLISTED_OPS)
    assert emitted == {"trim", "crop", "resize"}


def test_no_synthetic_workflow_op_is_emitted() -> None:
    """No node ever carries an op name outside the frozen registry."""

    variant = _variant(samples=_ready_samples(n=3))
    job = lower_variant_to_dag(variant, source_video=_source_video())
    allowed = set(OP_ADAPTERS)
    assert {node.kind for node in job.dag.nodes} <= allowed


# --- crop → resize → merge ordering -----------------------------------------


def test_lowered_nodes_follow_crop_resize_merge_ordering() -> None:
    """For a multi-segment ready variant, the emitted steps are crop → resize → merge."""

    variant = _variant(samples=_ready_samples(n=2))
    job = lower_variant_to_dag(variant, source_video=_source_video())
    kinds = [node.kind for node in job.dag.nodes]
    # crop, resize, crop, resize, merge
    assert kinds == ["crop", "resize", "crop", "resize", "merge"]
    # Each resize depends on its crop; merge depends on both resizes.
    crop_ids = [node.id for node in job.dag.nodes if node.kind == "crop"]
    resize_ids = [node.id for node in job.dag.nodes if node.kind == "resize"]
    for crop_id, resize_id in zip(crop_ids, resize_ids, strict=True):
        resize_node = next(node for node in job.dag.nodes if node.id == resize_id)
        assert crop_id in resize_node.depends_on
    merge_node = next(node for node in job.dag.nodes if node.kind == "merge")
    for resize_id in resize_ids:
        assert resize_id in merge_node.depends_on


def test_lowered_nodes_preserve_output_dimensions() -> None:
    """The resize step writes ``CropVariantPlan.output_width``/``output_height``."""

    variant = _variant(
        output_width=1080,
        output_height=1920,
        samples=_ready_samples(n=1),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    for node in job.dag.nodes:
        if node.kind == "resize":
            assert node.params["width"] == 1080
            assert node.params["height"] == 1920
    assert job.plan.output_width == 1080
    assert job.plan.output_height == 1920


def test_lowered_crop_uses_pixel_dimensions_from_normalized_box() -> None:
    """The crop step writes source-pixel width/height/x/y derived from the box."""

    variant = _variant(
        output_width=1080,
        output_height=1920,
        samples=(
            _track_sample(
                timestamp=0.0,
                box=(0.25, 0.25, 0.5, 0.5),
                source_w=960,
                source_h=540,
            ),
        ),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video(width=1920, height=1080))
    crop_node = next(node for node in job.dag.nodes if node.kind == "crop")
    assert "width" in crop_node.params
    assert "height" in crop_node.params
    assert "x" in crop_node.params
    assert "y" in crop_node.params
    assert crop_node.params["width"] > 0
    assert crop_node.params["height"] > 0


def test_lowered_dag_compiles_to_valid_workflow_spec() -> None:
    """The lowered DAG compiles to a workflow spec the existing parser accepts."""

    variant = _variant(samples=_ready_samples(n=2))
    job = lower_variant_to_dag(variant, source_video=_source_video())
    compiled = compile_lowered_job(job)
    parsed = parse_lowered_spec(compiled.spec)
    assert parsed.schema_version == 1
    step_ops = [step.op for step in parsed.steps]
    assert all(op in REFRAME_ALLOWLISTED_OPS for op in step_ops)


# --- deterministic lowering -------------------------------------------------


def test_lowering_is_deterministic() -> None:
    """Two runs over the same variant produce identical DAG identity + bytes."""

    variant = _variant(samples=_ready_samples(n=2))
    a = lower_variant_to_dag(variant, source_video=_source_video())
    b = lower_variant_to_dag(variant, source_video=_source_video())
    assert a.plan.plan_id == b.plan.plan_id
    assert a.plan.dag_identity == b.plan.dag_identity
    a_bytes = compile_dag_to_spec(a.dag).spec_bytes
    b_bytes = compile_dag_to_spec(b.dag).spec_bytes
    assert a_bytes == b_bytes


def test_lowering_via_reframe_plan_is_deterministic() -> None:
    """The wrapping ``ReframePlan`` entry-point produces the same identity."""

    plan = _reframe_plan((_variant(samples=_ready_samples(n=2)),))
    a = lower_reframe_to_dag(plan)
    b = lower_reframe_to_dag(plan)
    assert a.plan.dag_identity == b.plan.dag_identity
    assert a.plan.plan_id == b.plan.plan_id


def test_lowered_plan_id_matches_dag_identity_when_only_emitted_via_plan() -> None:
    """``LoweredClipPlan.dag_identity`` equals the live DAG's identity."""

    variant = _variant(samples=_ready_samples(n=1))
    job = lower_variant_to_dag(variant, source_video=_source_video())
    assert job.plan.dag_identity == dag_identity(job.dag)
    assert job.plan.plan_id.startswith("sha256:")


# --- low-confidence / abstained fallback -------------------------------------


def test_abstained_variant_lowers_to_safe_static_composition() -> None:
    """An abstained variant emits the static fallback DAG with PARTIAL warning."""

    variant = _variant(
        status="abstained",
        abstention_reasons=("tracking_loss",),
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    assert job.plan.status == "partial"
    assert job.plan.review_warnings
    assert any("PARTIAL" in warning for warning in job.plan.review_warnings)
    kinds = [node.kind for node in job.dag.nodes]
    assert "merge" not in kinds
    assert kinds == ["trim", "crop", "resize"]


def test_variant_with_abstention_reasons_lowers_to_safe_static_composition() -> None:
    """A variant with any abstention reason lowers to the fallback even if 'ready'."""

    variant = _variant(
        status="ready",
        abstention_reasons=("multi_subject_ambiguity",),
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    assert job.plan.status == "partial"
    assert any("multi_subject_ambiguity" in warning for warning in job.plan.review_warnings)


def test_static_fallback_uses_neutral_centre_crop_not_subject_box() -> None:
    """The fallback never encodes the possibly-wrong subject box."""

    # An abstained track whose crop box points at the bottom-right corner of
    # the frame; the static fallback should produce a centred crop, not the
    # subject-tracking box.
    variant = _variant(
        status="abstained",
        abstention_reasons=("no_face_detected",),
        samples=(
            _track_sample(
                timestamp=0.0,
                box=(0.7, 0.7, 0.2, 0.2),  # bottom-right corner
            ),
        ),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video(width=1920, height=1080))
    crop_node = next(node for node in job.dag.nodes if node.kind == "crop")
    # Centre crop on 1920x1080 → target 1080x1920 (vertical) → width = source_h *
    # target_aspect = 1080 * (1080/1920) ≈ 607, x ≈ (1920 - 608) / 2 = 656.
    assert abs(crop_node.params["x"] - (1920 - crop_node.params["width"]) // 2) <= 2
    assert abs(crop_node.params["y"] - (1080 - crop_node.params["height"]) // 2) <= 2
    assert crop_node.params["x"] >= 0
    assert crop_node.params["y"] >= 0


def test_static_fallback_warning_explicit_not_silent() -> None:
    """The reviewer warning is explicit and mentions every abstention reason."""

    variant = _variant(
        status="abstained",
        abstention_reasons=("tracking_loss", "subject_crop_budget_exceeded"),
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    warnings = " ".join(job.plan.review_warnings)
    assert "PARTIAL" in warnings
    assert "tracking_loss" in warnings
    assert "subject_crop_budget_exceeded" in warnings


def test_static_fallback_output_dimensions_match_variant() -> None:
    """The fallback resize enforces the variant's output_width/output_height."""

    variant = _variant(
        status="abstained",
        abstention_reasons=("no_face_detected",),
        output_width=720,
        output_height=1280,
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    resize_node = next(node for node in job.dag.nodes if node.kind == "resize")
    assert resize_node.params["width"] == 720
    assert resize_node.params["height"] == 1280
    assert job.plan.output_width == 720
    assert job.plan.output_height == 1280


def test_ready_plan_has_no_partial_warnings() -> None:
    """A ready variant's plan carries zero PARTIAL warnings."""

    variant = _variant(samples=_ready_samples(n=2))
    job = lower_variant_to_dag(variant, source_video=_source_video())
    assert job.plan.status == "ready"
    assert not any(w.startswith("PARTIAL") for w in job.plan.review_warnings)


def test_static_fallback_compiles_to_valid_workflow_spec() -> None:
    """The fallback DAG also compiles to a valid existing-spec."""

    variant = _variant(
        status="abstained",
        abstention_reasons=("no_face_detected",),
        samples=(_track_sample(timestamp=0.0, box=(0.25, 0.25, 0.5, 0.5)),),
    )
    job = lower_variant_to_dag(variant, source_video=_source_video())
    compiled = compile_lowered_job(job)
    parsed = parse_lowered_spec(compiled.spec)
    assert parsed.schema_version == 1
    step_ops = [step.op for step in parsed.steps]
    assert step_ops == ["trim", "crop", "resize"]


# --- variant validation ------------------------------------------------------


def test_lowered_clip_plan_partial_without_warning_is_rejected() -> None:
    """The strict model refuses a ``partial`` plan with zero warnings."""

    with pytest.raises(Exception):
        LoweredClipPlan(
            plan_id="sha256:" + "a" * 64,
            dag_identity="sha256:" + "b" * 64,
            target_id="t",
            status="partial",
            output_width=1080,
            output_height=1920,
            segment_count=1,
            used_ops=("crop", "resize"),
            review_warnings=(),
        )


def test_lowered_clip_plan_ready_with_partial_warning_is_rejected() -> None:
    """A ready plan must not carry PARTIAL warnings."""

    with pytest.raises(Exception):
        LoweredClipPlan(
            plan_id="sha256:" + "a" * 64,
            dag_identity="sha256:" + "b" * 64,
            target_id="t",
            status="ready",
            output_width=1080,
            output_height=1920,
            segment_count=1,
            used_ops=("crop", "resize"),
            review_warnings=("PARTIAL: oops",),
        )


def test_lowering_rejects_unknown_variant_index() -> None:
    """Out-of-range variant_index fails closed via the DAG validator."""

    plan = _reframe_plan((_variant(samples=_ready_samples(n=1)),))
    with pytest.raises(MCPVideoError):
        lower_reframe_to_dag(plan, variant_index=5)


def test_lowering_accepts_mapping_form_of_variant() -> None:
    """A loose dict form of the variant also lowers correctly."""

    mapping = {
        "target_id": "dict_var",
        "status": "ready",
        "abstention_reasons": [],
        "output_width": 1080,
        "output_height": 1920,
        "source_crop_fraction": 0.5,
        "maximum_subject_loss": 0.1,
        "crop_track": [
            {
                "timestamp_seconds": 0.0,
                "crop_box": {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4},
                "subject_coverage": 0.9,
                "safe_region_coverage": 1.0,
                "source_width": 768,
                "source_height": 432,
            }
        ],
        "previews": [],
    }
    job = lower_variant_to_dag(mapping, source_video=_source_video())
    assert job.plan.target_id == "dict_var"
    assert job.plan.status == "ready"


def test_isolated_segment_emits_trim_step() -> None:
    """``isolate_segments=True`` adds a ``trim`` step before each crop."""

    # timestamp=5.0 (not 0) so trim is emitted
    variant = _variant(samples=(_track_sample(timestamp=5.0, box=(0.2, 0.2, 0.4, 0.4)),))
    job = lower_variant_to_dag(variant, source_video=_source_video(), isolate_segments=True)
    kinds = [node.kind for node in job.dag.nodes]
    assert "trim" in kinds
    trim_node = next(node for node in job.dag.nodes if node.kind == "trim")
    assert trim_node.params["start"] == 5.0


def test_max_segments_caps_emit_count() -> None:
    """``max_segments`` limits the number of crop-track samples emitted."""

    variant = _variant(samples=_ready_samples(n=3))
    job = lower_variant_to_dag(variant, source_video=_source_video(), max_segments=2)
    crop_nodes = [node for node in job.dag.nodes if node.kind == "crop"]
    assert len(crop_nodes) == 2
    assert job.plan.segment_count == 2
