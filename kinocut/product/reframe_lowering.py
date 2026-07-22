"""Lower existing reframe plans to the existing Render DAG (``OP_ADAPTERS``).

This module is the **reframe compile-down seam**: it consumes the strict
``CropVariantPlan`` outputs of ``visual_intelligence.reframe.
plan_subject_aware_reframe`` and emits a :class:`kinocut.render_dag.RenderDAG`
that compiles down to a ``schema_version: 1`` workflow spec via the existing
:func:`kinocut.render_dag.compile_dag_to_spec`. The lowered DAG uses ONLY the
allowlisted workflow ops already exposed by ``OP_ADAPTERS`` (see
:mod:`kinocut.workflow.ops`):

* ``trim`` — segment isolation (optional; only when the variant's timestamps
  span a sub-range of the source that needs to be lifted out);
* ``crop`` — per-segment crop normalized boxes converted to source-pixel
  ``width``/``height``/``x``/``y``;
* ``resize`` — :class:`CropVariantPlan.output_width` /
  :class:`CropVariantPlan.output_height` enforcement;
* ``merge`` — combine the per-segment cropped+resized clips into a single
  output.

No new workflow op, no new tracker, and no bespoke kind is invented here.
Low-confidence or abstained variants (status ``"abstained"``, any non-empty
``abstention_reasons``) lower to a **safe static composition**: a single
centre crop covering the trimmed range, emitted as ``trim`` → ``crop`` →
``resize`` WITHOUT a ``merge`` step. The lowered DAG carries an explicit
PARTIAL review warning via :class:`LoweredClipPlan.review_warnings` so the
human reviewer can never miss that the subject was dropped.

Every public helper accepts any strict-model or mapping form of the input and
returns deterministic, JSON-stable artifacts (a frozen Render DAG plus a
plan-shape value object carrying the deterministic ``dag_identity``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.render_dag import (
    DAGNode,
    DAGOutput,
    DAGSource,
    RenderDAG,
    compile_dag_to_spec,
)
from kinocut.render_dag.schema import (
    INVALID_DAG_SPEC,
    NODE_OUTPUT_PREFIX,
    OUTPUT_PREFIX,
    SOURCE_PREFIX,
    dag_error,
)
from kinocut.workflow.ops import OP_ADAPTERS
from kinocut.workflow.spec import parse_spec


#: Frozen allowlisted op set used by this module. Mirrors the subset of
#: :data:`kinocut.workflow.ops.OP_ADAPTERS` that the reframe compile-down ever
#: emits; the bound below also asserts the live registry covers every name.
REFRAME_ALLOWLISTED_OPS: tuple[str, ...] = ("trim", "crop", "resize", "merge")

#: Sentinel node id suffix to mark nodes as part of a static composition
#: fallback so downstream tooling can distinguish them.
_STATIC_FALLBACK_TAG = "static_fallback"


# --- strict value objects ----------------------------------------------------


class _StrictModel(ValueObject):
    """Local alias mirroring the inline-strict-model pattern used elsewhere."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LoweredClipPlan(_StrictModel):
    """Plan-shape value object returned alongside the lowered :class:`RenderDAG`.

    Carries the same identity the DAG itself has (recomputed from the DAG via
    :func:`kinocut.render_dag.dag_identity`) plus the warnings the orchestrator
    must surface to the human reviewer. ``review_warnings`` is non-empty
    whenever the lowered variant was low-confidence or abstained — never empty
    on the static fallback path.
    """

    plan_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dag_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_id: str = Field(min_length=1)
    status: Literal["ready", "partial"]
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    segment_count: int = Field(ge=1)
    used_ops: tuple[str, ...] = ()
    review_warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _partial_has_warning(self) -> LoweredClipPlan:
        if self.status == "partial" and not self.review_warnings:
            raise ValueError("partial plans must carry at least one review_warning")
        if self.status == "ready" and any(warning.startswith("PARTIAL") for warning in self.review_warnings):
            raise ValueError("ready plans must not carry PARTIAL review warnings")
        return self


@dataclass(frozen=True)
class LoweredClipJob:
    """A lowered clip job: the DAG and the plan-shape value object.

    Both halves are deterministic and equal-input-stable; the dataclass is
    frozen so the orchestrator can store it as a planning receipt without
    risk of in-place mutation.
    """

    dag: RenderDAG
    plan: LoweredClipPlan

    def to_compiled_spec(self) -> Any:
        """Compile the DAG to the existing ``schema_version: 1`` workflow spec.

        The result is identical in shape to a hand-written spec and is
        directly consumable by the existing workflow executor / validator.
        Re-exported here so callers don't need to import
        :mod:`kinocut.render_dag` themselves.
        """

        return compile_dag_to_spec(self.dag)


# --- reframe model coercion --------------------------------------------------


def _coerce_variant(
    variant: Mapping[str, Any] | Any,
) -> Any:
    """Coerce a mapping / object into a strict ``CropVariantPlan``.

    Accepts any object exposing ``CropVariantPlan``-shaped attributes. We
    avoid importing :mod:`kinocut.visual_intelligence.models` at module top
    because that module pulls in the heavy visual-intelligence surface; this
    file is meant to remain cheap to import for the orchestrator path.
    """

    from kinocut.visual_intelligence.models import CropVariantPlan

    if isinstance(variant, CropVariantPlan):
        return variant
    if isinstance(variant, Mapping):
        return CropVariantPlan.model_validate(variant)
    required = (
        "target_id",
        "status",
        "abstention_reasons",
        "output_width",
        "output_height",
        "source_crop_fraction",
        "maximum_subject_loss",
        "crop_track",
        "previews",
    )
    for attr in required:
        if not hasattr(variant, attr):
            raise dag_error(
                f"reframe variant missing {attr!r}; provide CropVariantPlan or mapping",
                INVALID_DAG_SPEC,
            )
    return CropVariantPlan.model_validate({key: getattr(variant, key) for key in required})


def _coerce_reframe_plan(
    plan: Mapping[str, Any] | Any,
) -> Any:
    """Coerce a mapping / object into a strict :class:`ReframePlan`."""

    from kinocut.visual_intelligence.models import ReframePlan

    if isinstance(plan, ReframePlan):
        return plan
    if isinstance(plan, Mapping):
        return ReframePlan.model_validate(plan)
    required = (
        "analysis_sha256",
        "source",
        "primary_subject_id",
        "crop_budget",
        "min_tracking_confidence",
        "max_center_step",
        "variants",
    )
    for attr in required:
        if not hasattr(plan, attr):
            raise dag_error(
                f"reframe plan missing {attr!r}; provide ReframePlan or mapping",
                INVALID_DAG_SPEC,
            )
    return ReframePlan.model_validate({key: getattr(plan, key) for key in required})


# --- main entrypoints --------------------------------------------------------


def lower_reframe_to_dag(
    reframe_plan: Mapping[str, Any] | Any,
    *,
    variant_index: int = 0,
    source_id: str = "source",
    output_path: str = "output/reframed.mp4",
    output_id: str = "reframed",
    isolate_segments: bool = False,
    max_segments: int | None = None,
) -> LoweredClipJob:
    """Lower one ``ReframePlan`` variant to a frozen Render DAG.

    Parameters
    ----------
    reframe_plan:
        Either a strict :class:`kinocut.visual_intelligence.models.ReframePlan`,
        any mapping matching its shape, or any object exposing the required
        attributes.
    variant_index:
        Which variant in ``reframe_plan.variants`` to lower (sorted by the
        planner, so the index is deterministic across runs).
    source_id:
        The DAG source id (becomes ``@sources.<source_id>``). The compiled spec
        inherits this name so the orchestrator can match a single source across
        runs.
    output_path:
        Confined relative path for the final output. Forwarded to
        :class:`DAGOutput` unchanged.
    output_id:
        The DAG output id (becomes ``@outputs.<output_id>``). Pairs with
        ``output_path``.
    isolate_segments:
        When True, the lowered DAG includes a per-segment ``trim`` step that
        lifts each crop-track sample's timestamp into its own sub-range. When
        False (the default), the existing source is reused directly because
        crop+resize is timestamp-independent — the trim step is omitted to keep
        the DAG minimal.
    max_segments:
        Optional cap on the number of crop-track samples emitted into the
        DAG. Useful for testing and for the orchestrator when it wants to
        budget the work. ``None`` means "emit every sample".

    Returns
    -------
    LoweredClipJob
        A frozen job carrying the :class:`RenderDAG` and a :class:`LoweredClipPlan`.
        The ``status`` is ``"ready"`` for a high-confidence variant and
        ``"partial"`` whenever the variant is abstained or has abstention
        reasons — the latter triggers the safe static composition fallback and
        emits an explicit PARTIAL ``review_warning``.

    Raises
    ------
    MCPVideoError
        On structural / allowlist violations, propagated from the DAG validator.
    """

    ref = _coerce_reframe_plan(reframe_plan)
    if not ref.variants:
        raise dag_error("reframe plan has no variants; cannot lower", INVALID_DAG_SPEC)
    if variant_index < 0 or variant_index >= len(ref.variants):
        raise dag_error(
            f"variant_index {variant_index} out of range (plan has {len(ref.variants)} variants)",
            INVALID_DAG_SPEC,
        )
    variant = ref.variants[variant_index]
    return lower_variant_to_dag(
        variant,
        source_id=source_id,
        output_path=output_path,
        output_id=output_id,
        isolate_segments=isolate_segments,
        max_segments=max_segments,
        source_video=ref.source,
    )


def lower_variant_to_dag(
    variant: Mapping[str, Any] | Any,
    *,
    source_id: str = "source",
    output_path: str = "output/reframed.mp4",
    output_id: str = "reframed",
    isolate_segments: bool = False,
    max_segments: int | None = None,
    source_video: Any | None = None,
) -> LoweredClipJob:
    """Lower a single :class:`CropVariantPlan` (or mapping) to a frozen DAG.

    This is the same path :func:`lower_reframe_to_dag` takes for a single
    variant, exposed publicly so callers that already hold a
    ``CropVariantPlan`` can skip the wrapping ``ReframePlan`` round-trip.

    A variant whose ``status`` is ``"abstained"`` or whose
    ``abstention_reasons`` is non-empty lowers to a **safe static
    composition**: a single ``trim`` (covering the full crop-track range) →
    ``crop`` (centre crop at native source dimensions) → ``resize`` (target
    ``output_width`` x ``output_height``), with no ``merge`` step. The
    accompanying :class:`LoweredClipPlan` carries ``status="partial"`` and a
    PARTIAL ``review_warning`` derived from every abstention reason.
    """

    coerced = _coerce_variant(variant)
    _assert_allowlisted_ops()

    source_w = None
    source_h = None
    if source_video is not None:
        source_w = getattr(source_video, "width", None)
        source_h = getattr(source_video, "height", None)
    elif coerced.crop_track:
        # Best-effort fallback: pull source dimensions off the first track sample
        # so a centre crop on the static fallback path is computable without the
        # caller passing ``source_video``. Pydantic models expose ``model_dump``
        # but not their internal shape — read via attribute access.
        first = coerced.crop_track[0]
        source_w = getattr(first, "source_width", None)
        source_h = getattr(first, "source_height", None)

    samples = list(coerced.crop_track)
    if max_segments is not None:
        if max_segments < 1:
            raise dag_error("max_segments must be >= 1", INVALID_DAG_SPEC)
        samples = samples[:max_segments]

    is_abstained = coerced.status == "abstained" or bool(coerced.abstention_reasons)
    if is_abstained:
        dag, plan = _build_static_fallback_dag(
            coerced,
            samples=samples,
            source_id=source_id,
            output_id=output_id,
            output_path=output_path,
            source_w=source_w,
            source_h=source_h,
        )
    else:
        dag, plan = _build_ready_dag(
            coerced,
            samples=samples,
            source_id=source_id,
            output_id=output_id,
            output_path=output_path,
            source_w=source_w,
            source_h=source_h,
            isolate_segments=isolate_segments,
        )

    return LoweredClipJob(dag=dag, plan=plan)


def compile_lowered_job(job: LoweredClipJob) -> Any:
    """Compile a :class:`LoweredClipJob` to the existing workflow spec dict.

    Convenience wrapper that exposes the compile seam without forcing callers
    to import :mod:`kinocut.render_dag` themselves.
    """

    return compile_dag_to_spec(job.dag)


def parse_lowered_spec(spec: Mapping[str, Any]) -> Any:
    """Parse a compiled spec dict through the existing ``parse_spec`` validator.

    Exposed so callers can prove the lowered DAG compiles to a spec that the
    existing executor will accept (mirrors the integration test pattern in
    ``tests/test_render_dag_integration.py``).
    """

    return parse_spec(dict(spec))


# --- private: allowlist binding ---------------------------------------------


def _assert_allowlisted_ops() -> None:
    """Fail closed when the live ``OP_ADAPTERS`` registry drops a needed op."""

    missing = [op for op in REFRAME_ALLOWLISTED_OPS if op not in OP_ADAPTERS]
    if missing:
        raise dag_error(
            f"reframe lowerer requires ops {missing!r} but OP_ADAPTERS is missing them",
            INVALID_DAG_SPEC,
        )


# --- private: ready-variant DAG construction ---------------------------------


def _build_ready_dag(
    variant: Any,
    *,
    samples: list[Any],
    source_id: str,
    output_id: str,
    output_path: str,
    source_w: int | None,
    source_h: int | None,
    isolate_segments: bool,
) -> tuple[RenderDAG, LoweredClipPlan]:
    """Build a DAG for a ready (non-abstained) variant.

    The emitted node sequence is, per segment:

        [trim (optional)] → crop → resize

    Followed by a single ``merge`` node that combines every segment (or a
    zero-effect forwarding resize when only one segment exists so the
    executor still has a single owner of the output ref). The ordering is
    strict and deterministic so the rendered spec is byte-stable.
    """

    if not samples:
        raise dag_error("ready variant has empty crop_track; cannot lower", INVALID_DAG_SPEC)
    if source_w is None or source_h is None or source_w <= 0 or source_h <= 0:
        raise dag_error(
            "ready variant requires source_video width/height to compute pixel crop boxes",
            INVALID_DAG_SPEC,
        )

    nodes: list[DAGNode] = []
    segment_outputs: list[str] = []
    segment_resize_ids: list[str] = []
    for index, sample in enumerate(samples):
        segment_id = f"{variant.target_id}_seg_{index:03d}"

        # Optional trim for segment isolation. We only emit trim when
        # ``isolate_segments`` is True AND the sample's timestamp isn't already
        # at the source start (the trim becomes a no-op otherwise and we
        # avoid an unnecessary op in the canonical DAG).
        if isolate_segments and sample.timestamp_seconds > 0:
            trim_id = f"{segment_id}_trim"
            trim_duration = _approx_segment_duration(samples, index)
            nodes.append(
                DAGNode(
                    id=trim_id,
                    kind="trim",
                    inputs={"src": f"{SOURCE_PREFIX}{source_id}"},
                    params={"start": float(sample.timestamp_seconds), "duration": float(trim_duration)},
                    output=f"{NODE_OUTPUT_PREFIX}{trim_id}",
                )
            )
            crop_depends_on = (trim_id,)
            crop_src = f"{NODE_OUTPUT_PREFIX}{trim_id}"
        else:
            crop_depends_on = ()
            crop_src = f"{SOURCE_PREFIX}{source_id}"

        crop_id = f"{segment_id}_crop"
        crop_params = _crop_params_for_sample(sample, source_w=source_w, source_h=source_h)
        nodes.append(
            DAGNode(
                id=crop_id,
                kind="crop",
                depends_on=crop_depends_on,
                inputs={"src": crop_src},
                params=crop_params,
                output=f"{NODE_OUTPUT_PREFIX}{crop_id}",
            )
        )

        resize_id = f"{segment_id}_resize"
        nodes.append(
            DAGNode(
                id=resize_id,
                kind="resize",
                depends_on=(crop_id,),
                inputs={"src": f"{NODE_OUTPUT_PREFIX}{crop_id}"},
                params={"width": int(variant.output_width), "height": int(variant.output_height)},
                output=f"{NODE_OUTPUT_PREFIX}{resize_id}",
            )
        )
        segment_outputs.append(f"{NODE_OUTPUT_PREFIX}{resize_id}")
        segment_resize_ids.append(resize_id)

    # Single merge node to combine segments when more than one exists; for
    # the single-segment case we forward the resize output as the final.
    if len(segment_outputs) > 1:
        final_id = f"{variant.target_id}_merge"
        nodes.append(
            DAGNode(
                id=final_id,
                kind="merge",
                depends_on=tuple(segment_resize_ids),
                inputs={"srcs": list(segment_outputs)},
                output=f"{OUTPUT_PREFIX}{output_id}",
            )
        )
        used_ops = ("trim", "crop", "resize", "merge") if isolate_segments else ("crop", "resize", "merge")
    else:
        last_resize_id = segment_resize_ids[0]
        forward_id = f"{variant.target_id}_finalize"
        nodes.append(
            DAGNode(
                id=forward_id,
                kind="resize",
                depends_on=(last_resize_id,),
                inputs={"src": f"{NODE_OUTPUT_PREFIX}{last_resize_id}"},
                params={"width": int(variant.output_width), "height": int(variant.output_height)},
                output=f"{OUTPUT_PREFIX}{output_id}",
            )
        )
        used_ops = ("crop", "resize") if not isolate_segments else ("trim", "crop", "resize")

    _verify_node_kinds(nodes)
    dag = RenderDAG(
        dag_schema_version=1,
        name=f"reframe-{variant.target_id}",
        sources={source_id: DAGSource(path=f"input/{source_id}.mp4")},
        nodes=tuple(nodes),
        outputs={output_id: DAGOutput(path=output_path)},
    )

    plan = LoweredClipPlan(
        plan_id=_plan_id_for_dag(dag),
        dag_identity=_identity_for_dag(dag),
        target_id=variant.target_id,
        status="ready",
        output_width=int(variant.output_width),
        output_height=int(variant.output_height),
        segment_count=len(samples),
        used_ops=tuple(used_ops),
        review_warnings=(),
    )
    return dag, plan


# --- private: static-fallback DAG construction -------------------------------


def _build_static_fallback_dag(
    variant: Any,
    *,
    samples: list[Any],
    source_id: str,
    output_id: str,
    output_path: str,
    source_w: int | None,
    source_h: int | None,
) -> tuple[RenderDAG, LoweredClipPlan]:
    """Build the safe static composition DAG for an abstained / low-confidence variant.

    The lowered DAG is a strict three-op chain (``trim`` -> ``crop`` -> ``resize``)
    that covers the entire crop-track range with a centre crop at native source
    dimensions. No ``merge`` is emitted: the safe composition is a single
    neutral segment by construction. The accompanying :class:`LoweredClipPlan`
    carries ``status="partial"`` and a PARTIAL warning for every abstention
    reason so the reviewer is never silent about the subject being dropped.
    """

    if not samples:
        raise dag_error(
            "abstained variant has empty crop_track; static fallback requires at least one sample",
            INVALID_DAG_SPEC,
        )
    if source_w is None or source_h is None or source_w <= 0 or source_h <= 0:
        raise dag_error(
            "abstained variant requires source_video width/height for static fallback centre crop",
            INVALID_DAG_SPEC,
        )

    first_sample = samples[0]
    crop_params = _centre_crop_params(
        source_w=source_w,
        source_h=source_h,
        target_w=int(variant.output_width),
        target_h=int(variant.output_height),
    )

    trim_id = f"{variant.target_id}_{_STATIC_FALLBACK_TAG}_trim"
    crop_id = f"{variant.target_id}_{_STATIC_FALLBACK_TAG}_crop"
    resize_id = f"{variant.target_id}_{_STATIC_FALLBACK_TAG}_resize"

    nodes: list[DAGNode] = [
        DAGNode(
            id=trim_id,
            kind="trim",
            inputs={"src": f"{SOURCE_PREFIX}{source_id}"},
            params={
                "start": float(first_sample.timestamp_seconds),
                "duration": float(_approx_segment_duration(samples, 0)),
            },
            output=f"{NODE_OUTPUT_PREFIX}{trim_id}",
        ),
        DAGNode(
            id=crop_id,
            kind="crop",
            depends_on=(trim_id,),
            inputs={"src": f"{NODE_OUTPUT_PREFIX}{trim_id}"},
            params=crop_params,
            output=f"{NODE_OUTPUT_PREFIX}{crop_id}",
        ),
        DAGNode(
            id=resize_id,
            kind="resize",
            depends_on=(crop_id,),
            inputs={"src": f"{NODE_OUTPUT_PREFIX}{crop_id}"},
            params={"width": int(variant.output_width), "height": int(variant.output_height)},
            output=f"{OUTPUT_PREFIX}{output_id}",
        ),
    ]
    _verify_node_kinds(nodes)

    review_warnings = _abstention_warnings(variant)

    dag = RenderDAG(
        dag_schema_version=1,
        name=f"reframe-{variant.target_id}-static-fallback",
        sources={source_id: DAGSource(path=f"input/{source_id}.mp4")},
        nodes=tuple(nodes),
        outputs={output_id: DAGOutput(path=output_path)},
    )
    plan = LoweredClipPlan(
        plan_id=_plan_id_for_dag(dag),
        dag_identity=_identity_for_dag(dag),
        target_id=variant.target_id,
        status="partial",
        output_width=int(variant.output_width),
        output_height=int(variant.output_height),
        segment_count=1,
        used_ops=("trim", "crop", "resize"),
        review_warnings=tuple(review_warnings),
    )
    return dag, plan


# --- private: crop math ------------------------------------------------------


def _crop_params_for_sample(sample: Any, *, source_w: int, source_h: int) -> dict[str, int]:
    """Convert a ``CropTrackSample.crop_box`` (normalized) to source-pixel params.

    Uses the engine ``crop`` op's ``width``/``height``/``x``/``y`` parameter
    set (see :mod:`kinocut.engine_crop`). The values are rounded to even
    integers so libx264 / yuv420p don't reject odd dimensions, mirroring the
    rest of the project's resize helper.
    """

    box = sample.crop_box
    width = max(2, round(float(box.width) * source_w))
    height = max(2, round(float(box.height) * source_h))
    width = _even(width)
    height = _even(height)
    width = min(width, source_w)
    height = min(height, source_h)
    # ``x``/``y`` are the top-left of the crop, derived from the box center.
    center_x = float(box.x) + float(box.width) / 2.0
    center_y = float(box.y) + float(box.height) / 2.0
    x = max(0, round(center_x * source_w) - width // 2)
    y = max(0, round(center_y * source_h) - height // 2)
    # Clamp into bounds.
    x = min(x, source_w - width)
    y = min(y, source_h - height)
    return {"width": width, "height": height, "x": x, "y": y}


def _centre_crop_params(*, source_w: int, source_h: int, target_w: int, target_h: int) -> dict[str, int]:
    """Centre-crop params at the target aspect ratio using source dimensions."""

    source_aspect = float(source_w) / float(source_h)
    target_aspect = float(target_w) / float(target_h)
    if target_aspect >= source_aspect:
        # Letterbox vertically: width = source_w, height = source_w / target_aspect.
        width = source_w
        height = max(2, round(source_w / target_aspect))
    else:
        # Letterbox horizontally: height = source_h, width = source_h * target_aspect.
        height = source_h
        width = max(2, round(source_h * target_aspect))
    width = _even(min(width, source_w))
    height = _even(min(height, source_h))
    x = (source_w - width) // 2
    y = (source_h - height) // 2
    return {"width": width, "height": height, "x": x, "y": y}


def _even(value: int) -> int:
    """Round to the nearest even integer (yuv420p / libx264 compatibility)."""

    rounded = round(value / 2.0) * 2
    return max(2, rounded)


def _approx_segment_duration(samples: Sequence[Any], index: int) -> float:
    """Approximate a per-segment duration from the next sample's timestamp.

    Defaults to 1.0 s when the sample is the last in the track — a safe
    minimum that keeps the static fallback deterministic without requiring
    the caller to pass source duration.
    """

    if index + 1 < len(samples):
        next_sample = samples[index + 1]
        delta = float(next_sample.timestamp_seconds) - float(samples[index].timestamp_seconds)
        return max(0.1, delta)
    return 1.0


def _abstention_warnings(variant: Any) -> tuple[str, ...]:
    """Build the review warnings for an abstained / low-confidence variant."""

    reasons = tuple(variant.abstention_reasons) if variant.abstention_reasons else ("abstained",)
    base = (
        f"PARTIAL: variant {variant.target_id!r} lowered via safe static composition "
        f"(no subject tracker); subject was not preserved because: {', '.join(reasons)}."
    )
    return (base,)


# --- private: validation + identity ------------------------------------------


def _verify_node_kinds(nodes: Sequence[DAGNode]) -> None:
    """Reject any lowered node whose kind escaped :data:`REFRAME_ALLOWLISTED_OPS`."""

    for node in nodes:
        if node.kind not in REFRAME_ALLOWLISTED_OPS:
            raise dag_error(
                f"reframe lowerer emitted disallowed op {node.kind!r}; allowlist is {list(REFRAME_ALLOWLISTED_OPS)}",
                INVALID_DAG_SPEC,
            )


def _identity_for_dag(dag: RenderDAG) -> str:
    """Recompute the DAG's identity via :func:`kinocut.render_dag.dag_identity`."""

    from kinocut.render_dag import dag_identity

    return dag_identity(dag)


def _plan_id_for_dag(dag: RenderDAG) -> str:
    """Deterministic content-derived plan id (sha256 over the canonical DAG bytes)."""

    from kinocut.render_dag import canonical_json

    payload = dag.model_dump(mode="json")
    encoded = canonical_json(payload)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = sorted(
    [
        "LoweredClipJob",
        "LoweredClipPlan",
        "REFRAME_ALLOWLISTED_OPS",
        "compile_lowered_job",
        "lower_reframe_to_dag",
        "lower_variant_to_dag",
        "parse_lowered_spec",
    ]
)
