"""Execute an approved subject-aware crop track through the shared FFmpeg runner."""

from __future__ import annotations

import hashlib
from pathlib import Path

from kinocut.defaults import DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_REFRAME_PIXEL_FORMAT, DEFAULT_REFRAME_VIDEO_CODEC
from kinocut.errors import ValidationError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path, _validate_output_path
from kinocut.workflow._versions import ffmpeg_version

from .models import CropTrackSample, ReframePlan, StrictModel


class ReframeRenderReceipt(StrictModel):
    plan_sha256: str
    target_id: str
    ffmpeg_version: str | None
    output_sha256: str
    sample_count: int


def _axis_expression(samples: tuple[CropTrackSample, ...], axis: str, source_size: int) -> str:
    values = [round((sample.crop_box.x if axis == "x" else sample.crop_box.y) * source_size) for sample in samples]
    expression = str(values[-1])
    for index in range(len(samples) - 2, -1, -1):
        boundary = (samples[index].timestamp_seconds + samples[index + 1].timestamp_seconds) / 2.0
        expression = f"if(lt(t,{boundary:.6f}),{values[index]},{expression})"
    return expression


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def render_reframe_plan(input_path: str, output_path: str, plan: ReframePlan, target_id: str) -> ReframeRenderReceipt:
    """Render one ready variant; crop coordinates are derived only from the frozen plan."""

    source = _validate_input_path(input_path)
    target = _validate_output_path(output_path)
    variants = [variant for variant in plan.variants if variant.target_id == target_id]
    if len(variants) != 1 or variants[0].status != "ready":
        raise ValidationError("target_id", "must identify one ready reframe variant")
    variant = variants[0]
    if not variant.crop_track:
        raise ValidationError("crop_track", "ready reframe variant must contain samples")
    first = variant.crop_track[0]
    width = round(first.crop_box.width * plan.source.width)
    height = round(first.crop_box.height * plan.source.height)
    x_expression = _axis_expression(variant.crop_track, "x", plan.source.width)
    y_expression = _axis_expression(variant.crop_track, "y", plan.source.height)
    filter_graph = (
        f"crop={width}:{height}:'{x_expression}':'{y_expression}',scale={variant.output_width}:{variant.output_height}"
    )
    _run_ffmpeg(
        [
            "-i",
            source,
            "-vf",
            filter_graph,
            "-c:v",
            DEFAULT_REFRAME_VIDEO_CODEC,
            "-preset",
            DEFAULT_PRESET,
            "-crf",
            str(DEFAULT_CRF),
            "-pix_fmt",
            DEFAULT_REFRAME_PIXEL_FORMAT,
            "-c:a",
            "copy",
            target,
        ]
    )
    return ReframeRenderReceipt(
        plan_sha256=plan.plan_sha256,
        target_id=target_id,
        ffmpeg_version=ffmpeg_version(),
        output_sha256=_sha256(Path(target)),
        sample_count=len(variant.crop_track),
    )


__all__ = ["ReframeRenderReceipt", "render_reframe_plan"]
