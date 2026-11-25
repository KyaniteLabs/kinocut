"""Execute an approved subject-aware crop track through the shared FFmpeg runner."""

from __future__ import annotations

from kinocut.defaults import DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_REFRAME_PIXEL_FORMAT, DEFAULT_REFRAME_VIDEO_CODEC
from kinocut.engine_probe import _cache_key, probe
from kinocut.engine_runtime_utils import _run_video_only
from kinocut.errors import MCPVideoError, ValidationError
from kinocut.ffmpeg_helpers import (
    _atomic_output,
    _run_ffmpeg,
    _run_ffprobe_json,
    _validate_input_path,
    _validate_output_path,
)
from kinocut.source_identity import assert_source_identity, stream_source_identity
from kinocut.source_identity import stable_source_sha256 as _sha256
from kinocut.workflow._versions import ffmpeg_version

from .models import CropTrackSample, ReframePlan, StrictModel

_MAX_EXPRESSION_SEGMENTS = 256


class ReframeRenderReceipt(StrictModel):
    plan_sha256: str
    target_id: str
    ffmpeg_version: str | None
    output_sha256: str
    sample_count: int


def _even_floor(value: int, maximum: int) -> int:
    clamped = max(2, min(maximum, value))
    even = clamped - (clamped % 2)
    return max(2, even)


def _even_ceil(value: int) -> int:
    return max(2, value + (value % 2))


def _balanced_piecewise(boundaries: list[float], values: list[int], time_expr: str = "t") -> str:
    """Build a balanced binary decision tree so FFmpeg eval depth stays O(log N)."""
    if len(values) == 1:
        return str(values[0])
    mid = len(values) // 2
    left = _balanced_piecewise(boundaries[: mid - 1], values[:mid], time_expr)
    right = _balanced_piecewise(boundaries[mid:], values[mid:], time_expr)
    return f"if(lt({time_expr},{boundaries[mid - 1]:.6f}),{left},{right})"


def _axis_expression(
    samples: tuple[CropTrackSample, ...],
    axis: str,
    source_size: int,
    max_origin: int | None = None,
    time_offset: float = 0.0,
) -> str:
    raw_values = [round((sample.crop_box.x if axis == "x" else sample.crop_box.y) * source_size) for sample in samples]
    if max_origin is not None:
        raw_values = [max(0, min(max_origin, val)) for val in raw_values]
    # Collapse consecutive identical coordinate values to shrink expression size.
    seg_values: list[int] = [raw_values[0]]
    seg_boundaries: list[float] = []
    for index in range(1, len(samples)):
        val = raw_values[index]
        if val != seg_values[-1]:
            boundary = (samples[index - 1].timestamp_seconds + samples[index].timestamp_seconds) / 2.0 + time_offset
            seg_boundaries.append(boundary)
            seg_values.append(val)
    # Downsample uniformly if still very large so CLI arg & eval depth remain bounded.
    if len(seg_values) > _MAX_EXPRESSION_SEGMENTS:
        step = (len(seg_values) - 1) / (_MAX_EXPRESSION_SEGMENTS - 1)
        picked = [round(i * step) for i in range(_MAX_EXPRESSION_SEGMENTS)]
        seg_values = [seg_values[i] for i in picked]
        seg_boundaries = [seg_boundaries[picked[i + 1] - 1] for i in range(len(picked) - 1)]
    return _balanced_piecewise(seg_boundaries, seg_values)


def _source_start_time(source: str) -> float:
    try:
        raw = _run_ffprobe_json(source)
        for stream in raw.get("streams", []):
            if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic"):
                val = stream.get("start_time")
                if val is not None:
                    parsed = float(val)
                    if parsed == parsed and abs(parsed) < 1e9:
                        return parsed
        fmt_val = raw.get("format", {}).get("start_time")
        if fmt_val is not None:
            parsed = float(fmt_val)
            if parsed == parsed and abs(parsed) < 1e9:
                return parsed
    except Exception:
        return 0.0
    return 0.0


def _build_reframe_filter_graph(
    plan: ReframePlan,
    variant: object,
    source_info: object,
    start_time: float,
) -> str:
    # Normalize SAR to square display pixels and pad to even dimensions before cropping.
    eff_w = _even_ceil(
        (getattr(source_info, "display_width", None) if source_info is not None else None) or plan.source.width
    )
    eff_h = _even_ceil(
        (getattr(source_info, "display_height", None) if source_info is not None else None) or plan.source.height
    )
    first = variant.crop_track[0]
    width = _even_floor(round(first.crop_box.width * eff_w), eff_w)
    height = _even_floor(round(first.crop_box.height * eff_h), eff_h)
    max_x = max(0, eff_w - width)
    max_y = max(0, eff_h - height)
    x_expression = _axis_expression(variant.crop_track, "x", eff_w, max_origin=max_x, time_offset=start_time)
    y_expression = _axis_expression(variant.crop_track, "y", eff_h, max_origin=max_y, time_offset=start_time)
    out_w = _even_ceil(variant.output_width)
    out_h = _even_ceil(variant.output_height)
    return (
        f"scale={eff_w}:{eff_h},setsar=1,"
        f"crop={width}:{height}:'{x_expression}':'{y_expression}',"
        f"scale={out_w}:{out_h},setsar=1"
    )


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
    identity = stream_source_identity(source)
    if identity.asset_id != plan.source.sha256:
        raise MCPVideoError(
            "Reframe plan source identity changed; analyze and replan",
            error_type="validation_error",
            code="source_identity_changed",
        )
    source_key = _cache_key(source)
    source_info = probe(source)
    start_time = _source_start_time(source)
    filter_graph = _build_reframe_filter_graph(plan, variant, source_info, start_time)
    with _atomic_output(target) as staged:
        _run_video_only(
            _run_ffmpeg,
            [
                "-i",
                source,
                "-vf",
                filter_graph,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
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
                staged,
            ],
        )
        probe(staged)
        assert_source_identity(source, identity)
        if _cache_key(source) != source_key:
            raise MCPVideoError(
                "Reframe source changed during rendering", error_type="validation_error", code="source_identity_changed"
            )
        receipt = ReframeRenderReceipt(
            plan_sha256=plan.plan_sha256,
            target_id=target_id,
            ffmpeg_version=ffmpeg_version(),
            output_sha256=_sha256(staged),
            sample_count=len(variant.crop_track),
        )
    return receipt


__all__ = ["ReframeRenderReceipt", "render_reframe_plan"]
