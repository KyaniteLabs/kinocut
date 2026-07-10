"""Timeline editing operation for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile

from .engine_audio_ops import add_audio
from .engine_edit import trim
from .engine_export import export_video
from .engine_merge import merge
from .engine_probe import probe
from .engine_resize import resize
from .engine_runtime_utils import (
    _default_font,
)
from .paths import (
    _auto_output,
)
from .models import (
    _position_coords,
    _validate_position,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .validation import (
    _validate_color,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _validate_input_path, _validate_output_path
from .models import EditResult, NamedPosition, Timeline, TimelineClip, TimelineImageOverlay


def edit_timeline(timeline: Timeline | dict, output_path: str | None = None) -> EditResult:
    """Execute a full timeline-based edit described in JSON."""
    if isinstance(timeline, dict):
        timeline = Timeline.model_validate(timeline)
    _validate_timeline_positions(timeline)
    tmpdir = tempfile.mkdtemp(prefix="mcp_video_timeline_")
    try:
        video_clips, audio_clips, text_elements, image_overlays = _collect_tracks(timeline, tmpdir)
        if not video_clips:
            raise MCPVideoError("Timeline must have at least one video clip")

        current = _merge_timeline_video(video_clips, timeline, tmpdir)
        if text_elements or image_overlays:
            composited = os.path.join(tmpdir, "composited.mp4")
            _apply_composite_overlays(current, composited, text_elements, image_overlays)
            current = composited

        if audio_clips:
            current = _apply_timeline_audio(current, audio_clips, tmpdir)

        if timeline.width and timeline.height:
            info = probe(current)
            if info.width != timeline.width or info.height != timeline.height:
                resized = os.path.join(tmpdir, "resized.mp4")
                resize(current, width=timeline.width, height=timeline.height, output_path=resized)
                current = resized

        output = output_path or _auto_output(video_clips[0], "timeline", ext=f".{timeline.export.format}")
        _validate_output_path(output)
        return export_video(current, output_path=output, quality=timeline.export.quality, format=timeline.export.format)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _apply_timeline_audio(current: str, audio_clips: list[TimelineClip], tmpdir: str) -> str:
    """Attach every timeline audio clip, honoring each clip's timing/volume/fade.

    The first audio clip establishes the base audio track (replacing the source
    audio, matching the original single-clip behavior). Every subsequent clip is
    layered on top with ``mix=True`` so additional voiceover/music tracks are not
    silently dropped. Each clip's ``start`` maps to ``start_time`` and its
    ``volume``/``fade_in``/``fade_out`` are forwarded to ``add_audio`` rather than
    being discarded.
    """
    for index, clip in enumerate(audio_clips):
        layered = os.path.join(tmpdir, f"with_audio_{index:04d}.mp4")
        add_audio(
            current,
            audio_path=clip.source,
            volume=clip.volume,
            fade_in=clip.fade_in,
            fade_out=clip.fade_out,
            start_time=clip.start if clip.start else None,
            mix=index > 0,
            output_path=layered,
        )
        current = layered
    return current


def _validate_timeline_positions(timeline: Timeline) -> None:
    for track in timeline.tracks:
        for elem in track.elements:
            _validate_position(elem.position)
        for img in track.images:
            _validate_position(img.position)


def _collect_tracks(timeline: Timeline, tmpdir: str):
    video_clips: list[str] = []
    audio_clips: list[TimelineClip] = []
    text_elements: list = []
    image_overlays: list[TimelineImageOverlay] = []

    for track in timeline.tracks:
        if track.type == "video":
            for clip in track.clips:
                _validate_input_path(clip.source)
                # Trim whenever any window is requested: a start offset, an
                # explicit end, OR a duration. ``duration`` is an independent
                # trigger so a clip with ``trim_start=0`` and ``duration`` set
                # (no ``trim_end``) is still trimmed instead of appended whole
                # (see #6). Precedence when both are present: ``trim_end`` wins,
                # because it pins an absolute end on the source timeline.
                if clip.trim_start > 0 or clip.trim_end is not None or clip.duration is not None:
                    trimmed = os.path.join(tmpdir, f"v_{len(video_clips):04d}.mp4")
                    trim_kwargs = {"start": clip.trim_start}
                    if clip.trim_end is not None:
                        trim_kwargs["end"] = clip.trim_end
                    elif clip.duration is not None:
                        trim_kwargs["duration"] = clip.duration
                    result = trim(clip.source, output_path=trimmed, **trim_kwargs)
                    video_clips.append(result.output_path)
                else:
                    video_clips.append(clip.source)
            text_elements.extend(track.elements)
        elif track.type == "audio":
            for clip in track.clips:
                _validate_input_path(clip.source)
                audio_clips.append(clip)
        elif track.type == "text":
            text_elements.extend(track.elements)
        elif track.type == "image":
            for img in track.images:
                _validate_input_path(img.source)
                image_overlays.append(img)
    return video_clips, audio_clips, text_elements, image_overlays


def _merge_timeline_video(video_clips: list[str], timeline: Timeline, tmpdir: str) -> str:
    if len(video_clips) == 1:
        return video_clips[0]
    merged = os.path.join(tmpdir, "merged.mp4")
    transition_list = None
    trans_duration = 1.0
    for track in timeline.tracks:
        if track.type == "video" and track.transitions:
            sorted_trans = sorted(track.transitions, key=lambda t: t.after_clip)
            transition_list = [t.type for t in sorted_trans]
            trans_duration = sorted_trans[0].duration
            break
    merge(video_clips, output_path=merged, transitions=transition_list, transition_duration=trans_duration)
    return merged


def _apply_composite_overlays(
    input_path: str,
    output_path: str,
    text_elements: list,
    image_overlays: list[TimelineImageOverlay],
) -> None:
    """Apply text and image overlays in a single FFmpeg filtergraph pass."""
    info = probe(input_path)
    inputs: list[str] = ["-i", input_path]
    filter_parts: list[str] = []
    input_idx = 1

    overlay_position_map: dict[NamedPosition, str] = {
        "top-left": "0:0",
        "top-center": "(main_w-overlay_w)/2:0",
        "top-right": "main_w-overlay_w:0",
        "center-left": "0:(main_h-overlay_h)/2",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        "center-right": "main_w-overlay_w:(main_h-overlay_h)/2",
        "bottom-left": "0:main_h-overlay_h",
        "bottom-center": "(main_w-overlay_w)/2:main_h-overlay_h",
        "bottom-right": "main_w-overlay_w:main_h-overlay_h",
    }

    prev_label = "0:v"
    for i, img in enumerate(image_overlays):
        img_label = f"img{i}"
        ov_label = f"ov{i}"
        inputs.extend(["-i", img.source])
        chain = _image_overlay_chain(img)
        filter_parts.append(f"[{input_idx}:v]{chain}[{img_label}]")
        pos = _image_overlay_position(img, overlay_position_map)
        enable_expr = _image_enable_expression(img)
        filter_parts.append(f"[{prev_label}][{img_label}]overlay={pos}{enable_expr}[{ov_label}]")
        prev_label = ov_label
        input_idx += 1

    vf_parts = [_drawtext_filter(elem, info.width, info.height) for elem in text_elements]
    _run_overlay_command(inputs, filter_parts, vf_parts, prev_label, image_overlays, output_path)


def _image_overlay_chain(img: TimelineImageOverlay) -> str:
    chain_parts: list[str] = []
    if img.width and img.height:
        chain_parts.append(f"scale={img.width}:{img.height}")
    elif img.width:
        chain_parts.append(f"scale={img.width}:-1")
    elif img.height:
        chain_parts.append(f"scale=-1:{img.height}")
    if img.opacity < 1.0:
        chain_parts.append("format=rgba")
        chain_parts.append(f"colorchannelmixer=aa={img.opacity:.2f}")
    return ",".join(chain_parts) if chain_parts else "null"


def _image_overlay_position(img: TimelineImageOverlay, overlay_position_map: dict[NamedPosition, str]) -> str:
    if isinstance(img.position, dict):
        if "x_pct" in img.position and "y_pct" in img.position:
            return f"(main_w*{img.position['x_pct']}-overlay_w/2):(main_h*{img.position['y_pct']}-overlay_h/2)"
        if "x" in img.position and "y" in img.position:
            return f"{img.position['x']}:{img.position['y']}"
        raise MCPVideoError(
            "Position dict must have 'x'+'y' (pixels) or 'x_pct'+'y_pct' (percentage)",
            error_type="validation_error",
            code="invalid_position_dict",
        )
    if img.x is not None and img.y is not None:
        return f"{img.x}:{img.y}"
    return overlay_position_map[img.position]


def _image_enable_expression(img: TimelineImageOverlay) -> str:
    if img.start is None and img.duration is None:
        return ""
    parts = []
    if img.start is not None and img.duration is not None:
        end = img.start + img.duration
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(img.start, "img.start")))
        safe_end = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(end, "end")))
        parts.append(f"between(t,{safe_start},{safe_end})")
    elif img.start is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(img.start, "img.start")))
        parts.append(f"gte(t,{safe_start})")
    elif img.duration is not None:
        safe_dur = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(img.duration, "img.duration")))
        parts.append(f"lte(t,{safe_dur})")
    return f":enable='{parts[0]}'"


def _drawtext_filter(elem, width: int, height: int) -> str:
    fontfile = elem.style.get("font") or _default_font()
    if fontfile is not None:
        fontfile = _escape_ffmpeg_filter_value(fontfile)
    size = elem.style.get("size", 48)
    color = elem.style.get("color", "white")
    _validate_color(color)
    coords = _position_coords(elem.position, width, height)
    escaped_text = _escape_ffmpeg_filter_value(elem.text)
    drawtext_parts = [
        f"drawtext=text='{escaped_text}'",
        "expansion=none",
        f"fontsize={size}",
        f"fontcolor={color}",
        f"fontfile={fontfile}",
        coords,
    ]
    if elem.style.get("shadow", True):
        drawtext_parts.append("shadowcolor=black@0.5")
        drawtext_parts.append("shadowx=2")
        drawtext_parts.append("shadowy=2")
    if elem.start is not None and elem.duration is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(elem.start, "elem.start")))
        safe_end = _escape_ffmpeg_filter_value(
            str(_sanitize_ffmpeg_number(elem.start + elem.duration, "elem.start + elem.duration"))
        )
        drawtext_parts.append(f"enable='between(t\\,{safe_start}\\,{safe_end})'")
    elif elem.start is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(elem.start, "elem.start")))
        drawtext_parts.append(f"enable='gte(t\\,{safe_start})'")
    return ":".join(drawtext_parts)


def _run_overlay_command(
    inputs: list[str],
    filter_parts: list[str],
    vf_parts: list[str],
    prev_label: str,
    image_overlays: list[TimelineImageOverlay],
    output_path: str,
) -> None:
    if image_overlays and vf_parts:
        last_label = prev_label
        for vf in vf_parts:
            filter_parts.append(f"[{last_label}]{vf}[vout]")
            last_label = "vout"
        _run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                ";".join(filter_parts),
                *_encode_args(output_path, extra=["-map", f"[{last_label}]", "-map", "0:a?"]),
            ]
        )
    elif image_overlays:
        _run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                ";".join(filter_parts),
                *_encode_args(output_path, extra=["-map", f"[{prev_label}]", "-map", "0:a?"]),
            ]
        )
    elif vf_parts:
        _run_ffmpeg([*inputs, "-vf", ",".join(vf_parts), *_encode_args(output_path)])


def _encode_args(output_path: str, extra: list[str] | None = None) -> list[str]:
    return _build_ffmpeg_cmd(
        output_path=output_path,
        video_codec="libx264",
        audio_codec="copy",
        extra=extra,
    )
