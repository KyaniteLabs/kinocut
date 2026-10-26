"""One-call, local-only shorts assembly over the existing edit engines."""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..engine_edit import trim
from ..engine_merge import merge
from ..engine_resize import resize
from ..engine_subtitle_generate import generate_subtitles
from ..engine_subtitles import subtitles
from ..ffmpeg_helpers import _validate_input_path

__all__ = ["video_shorts"]


def _flow_error(message: str, code: str = "invalid_parameter") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _segment_parts(segment: Mapping[str, Any] | Sequence[Any], index: int) -> tuple[float, float, str | None]:
    if isinstance(segment, Mapping):
        start, end, text = segment.get("start"), segment.get("end"), segment.get("text")
    elif isinstance(segment, Sequence) and not isinstance(segment, (str, bytes)) and len(segment) in {2, 3}:
        start, end = segment[0], segment[1]
        text = segment[2] if len(segment) == 3 else None
    else:
        raise _flow_error(f"segment {index} must provide start and end")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(float(start))
        or not math.isfinite(float(end))
    ):
        raise _flow_error(f"segment {index} start and end must be finite numbers")
    start_f, end_f = float(start), float(end)
    if start_f < 0 or end_f <= start_f:
        raise _flow_error(f"segment {index} end must be greater than start and start must be non-negative")
    if text is not None and not isinstance(text, str):
        raise _flow_error(f"segment {index} text must be a string when provided")
    return start_f, end_f, text


def _style_options(style: str | Mapping[str, Any] | None) -> tuple[str | None, str]:
    if style is None:
        return None, "high"
    if isinstance(style, str):
        return style, "high"
    if not isinstance(style, Mapping):
        raise _flow_error("style must be a string or object")
    caption_style = style.get("caption_style") or style.get("subtitle_style")
    if caption_style is not None and not isinstance(caption_style, str):
        raise _flow_error("style.caption_style must be a string")
    quality = style.get("quality", "high")
    if quality not in {"low", "medium", "high", "ultra"}:
        raise _flow_error("style.quality must be low, medium, high, or ultra")
    return caption_style, quality


def _default_output(input_path: str) -> str:
    path = Path(input_path)
    return str(path.with_name(f"{path.stem}_shorts{path.suffix or '.mp4'}"))


def video_shorts(
    input_path: str,
    segments: Sequence[Mapping[str, Any] | Sequence[Any]],
    style: str | Mapping[str, Any] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Trim, caption, make vertical, and export selected segments in one call.

    ``segments`` accepts mappings with ``start``, ``end``, and optional ``text``
    or compact ``(start, end[, text])`` sequences.  All work stays local and
    uses the existing trim, merge, subtitle, and resize engines.
    """

    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)) or not segments:
        raise _flow_error("segments must be a non-empty list")
    parsed = [_segment_parts(segment, index) for index, segment in enumerate(segments)]
    source = _validate_input_path(input_path)
    caption_style, quality = _style_options(style)
    final_output = output_path or _default_output(source)

    with tempfile.TemporaryDirectory(prefix="kinocut-shorts-") as workdir:
        trimmed_paths: list[str] = []
        for index, (start, end, _text) in enumerate(parsed):
            trimmed = os.path.join(workdir, f"segment-{index:03d}.mp4")
            result = trim(source, start=start, end=end, output_path=trimmed, accurate=True)
            trimmed_paths.append(result.output_path)

        if len(trimmed_paths) == 1:
            assembled_path = trimmed_paths[0]
            merge_step: dict[str, Any] = {"stage": "merge", "status": "skipped", "reason": "one segment"}
        else:
            assembled_path = os.path.join(workdir, "assembled.mp4")
            merged = merge(trimmed_paths, output_path=assembled_path)
            assembled_path = merged.output_path
            merge_step = {"stage": "merge", "status": "completed"}

        caption_entries: list[dict[str, Any]] = []
        offset = 0.0
        for start, end, text in parsed:
            if text:
                caption_entries.append({"start": offset, "end": offset + (end - start), "text": text})
            offset += end - start

        captioned_path = assembled_path
        if caption_entries:
            subtitle_path = str(Path(final_output).with_suffix(".srt"))
            generated = generate_subtitles(caption_entries, assembled_path, output_path=subtitle_path, burn=False)
            captioned_path = os.path.join(workdir, "captioned.mp4")
            subtitles(
                assembled_path,
                generated.srt_path,
                output_path=captioned_path,
                style=caption_style,
            )
            caption_step = {
                "stage": "captions",
                "status": "completed",
                "subtitle_path": generated.srt_path,
                "entry_count": len(caption_entries),
            }
        else:
            caption_step = {"stage": "captions", "status": "skipped", "reason": "segments have no text"}

        vertical = resize(
            captioned_path,
            aspect_ratio="9:16",
            quality=quality,
            output_path=final_output,
        )
        steps = [
            {"stage": "trim", "status": "completed", "segment_count": len(trimmed_paths)},
            merge_step,
            caption_step,
            {
                "stage": "vertical_template",
                "status": "completed",
                "aspect_ratio": "9:16",
                "output_path": vertical.output_path,
            },
            {"stage": "export", "status": "completed", "output_path": vertical.output_path},
        ]
        return {
            "success": True,
            "operation": "video_shorts",
            "output_path": vertical.output_path,
            "external_posting": False,
            "receipt": {
                "schema_version": 1,
                "receipt_kind": "video_shorts",
                "steps": steps,
            },
        }
