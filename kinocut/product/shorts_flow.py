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
from ..ffmpeg_helpers import _validate_input_path, _validate_output_path

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


def _assemble_segments(
    source: str,
    parsed: list[tuple[float, float, str | None]],
    workdir: str,
) -> tuple[list[str], str, dict[str, Any]]:
    """Trim every segment, then merge the trims into one assembled master."""

    trimmed_paths: list[str] = []
    for index, (start, end, _text) in enumerate(parsed):
        trimmed = os.path.join(workdir, f"segment-{index:03d}.mp4")
        result = trim(source, start=start, end=end, output_path=trimmed, accurate=True)
        trimmed_paths.append(result.output_path)

    if len(trimmed_paths) == 1:
        return trimmed_paths, trimmed_paths[0], {"stage": "merge", "status": "skipped", "reason": "one segment"}
    assembled_path = os.path.join(workdir, "assembled.mp4")
    merged = merge(trimmed_paths, output_path=assembled_path)
    return trimmed_paths, merged.output_path, {"stage": "merge", "status": "completed"}


def _measured_segment_durations(paths: list[str]) -> list[float]:
    """Measure each rendered trim so caption timing matches the shipped media.

    The requested ``end - start`` is what the caller asked for; what actually
    renders can be shorter, and a caption timed from the request can sit past
    the media. A trim that cannot be measured is not guessed at: the flow
    refuses, because a silent fallback is exactly how the caption timeline
    drifts out of the picture (t_e3775201 F7, Gate 4 NEW-6).
    """
    from ..engine_probe import probe as _probe_source

    measured: list[float] = []
    for index, path in enumerate(paths):
        try:
            value = float(_probe_source(path).duration or 0.0)
        except (OSError, ValueError, MCPVideoError) as exc:
            raise _flow_error(f"could not measure the rendered trim for segment {index}") from exc
        if value <= 0:
            raise _flow_error(f"could not measure the rendered trim for segment {index}")
        measured.append(value)
    return measured


_CAPTION_TEXT_LIMIT = 240
_RECEIPT_ENTRY_LIMIT = 50
# The source probe rounds to the centisecond, so a segment may end a hair past
# the measured EOF without really exceeding it. This tolerance is the accepted
# boundary; anything beyond it is refused.
_SOURCE_EOF_TOLERANCE = 0.05


def _caption_receipt(
    caption_entries: list[dict[str, Any]],
    generated: Any,
    truncated_captions: int,
) -> dict[str, Any]:
    """The caption stage receipt: what was burned, and what can be evidenced.

    A count the generator reported but returned no list for cannot be verified,
    so it is never presented as the burned count.
    """
    warnings = list(getattr(generated, "warnings", []) or [])
    generated_count = getattr(generated, "entry_count", None)
    generated_entries = list(getattr(generated, "entries", None) or [])
    requested_count = len(caption_entries)
    requested_entries = caption_entries
    if truncated_captions:
        warnings.append(f"{truncated_captions} caption(s) were truncated to {_CAPTION_TEXT_LIMIT} characters")
    count_unverified = False
    evidenced = bool(generated_entries)
    if generated_entries:
        burned_entries = generated_entries
        burned_count = len(burned_entries)
        if isinstance(generated_count, int) and generated_count != burned_count:
            count_unverified = True
            warnings.append(
                f"subtitle generator reported {generated_count} entries but returned {burned_count}; "
                "the returned list is used and the count is unverified"
            )
    else:
        # No list means no evidence of the burn, so there is no burned count
        # to report. The receipt carries the request and says the burn is
        # unevidenced, rather than presenting the request as what was burned.
        burned_entries = []
        burned_count = None
        # No list means no evidence of the burn. A count that happens to match
        # the request is still a count nobody can evidence, so it stays
        # unverified.
        count_unverified = True
        warnings.append(
            "the subtitle generator returned no entry list; the burned count is unverified "
            "and the requested captions are listed"
        )
        if isinstance(generated_count, int):
            warnings.append(
                f"subtitle generator reported {generated_count} entries and returned no list; "
                "the count is reported as rendered but cannot be evidenced"
            )
    if evidenced and burned_count is not None and burned_count != requested_count:
        dropped = requested_count - burned_count
        noun = "caption was" if dropped == 1 else "captions were"
        warnings.append(f"{dropped} requested {noun} not burned")
    carried = burned_entries[:_RECEIPT_ENTRY_LIMIT]
    carried_requested = requested_entries[:_RECEIPT_ENTRY_LIMIT]
    requested_truncated = max(0, len(requested_entries) - len(carried_requested))
    if requested_truncated:
        warnings.append(
            f"{requested_truncated} requested caption entries are not listed in this receipt; "
            "the count above is the whole request"
        )
    caption_step = {
        "stage": "captions",
        "status": "completed",
        "entry_count": burned_count,
        "requested_entry_count": requested_count,
        "burned_entry_count": burned_count,
        "count_unverified": count_unverified,
        "burned_evidence": "generator_list" if evidenced else "requested_only",
        "entries": carried,
        "requested_entries": carried_requested,
        "entries_truncated": max(0, (burned_count or 0) - len(carried)),
        "requested_entries_truncated": requested_truncated,
        # The SRT is a transient build input inside the flow-owned workdir, so
        # there is no durable path to report. The key stays for readers that
        # expect it; the value is honestly empty.
        "subtitle_path": None,
        "warnings": warnings,
    }
    if isinstance(generated_count, int):
        caption_step["rendered_entry_count"] = generated_count
    return caption_step


def _apply_captions(
    parsed: list[tuple[float, float, str | None]],
    measured: list[float],
    assembled_path: str,
    caption_style: str | None,
    final_output: str,
    workdir: str,
    truncated_captions: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Burn segment captions onto the assembled master, offset per segment."""

    if not any(text for (_start, _end, text) in parsed):
        # No caption needs a timeline, so the render needs no measured
        # durations: a segment that cannot be timed does not block a flow
        # that never reads a timing.
        return assembled_path, {"stage": "captions", "status": "skipped", "reason": "segments have no text"}

    if len(measured) != len(parsed):
        # The caption timeline is timed from the media that actually rendered.
        # A short measurement list cannot time the captions, and falling back
        # to the requested span is exactly the drift this flow refuses.
        raise _flow_error(
            "the measured segment durations do not match the requested segments; refusing to time the captions"
        )

    caption_entries: list[dict[str, Any]] = []
    offset = 0.0
    for index, (_start, _end, text) in enumerate(parsed):
        # The caption timeline follows the media that actually rendered, not
        # the requested range: a trim can be shorter than asked for, and a
        # caption timed from the request would sit past the media (F7).
        span = measured[index]
        if text:
            caption_entries.append({"start": offset, "end": offset + span, "text": text})
        offset += span

    if not caption_entries:
        return assembled_path, {"stage": "captions", "status": "skipped", "reason": "segments have no text"}
    # The SRT is a transient build input, not a durable sidecar: it lives in the
    # flow-owned workdir so a re-run with overwrite consent is never blocked by
    # a stale companion file next to the requested output.
    subtitle_path = os.path.join(workdir, "captions.srt")
    generated = generate_subtitles(caption_entries, assembled_path, output_path=subtitle_path, burn=False)
    captioned_path = os.path.join(workdir, "captioned.mp4")
    subtitles(
        assembled_path,
        generated.srt_path,
        output_path=captioned_path,
        style=caption_style,
    )
    return captioned_path, _caption_receipt(caption_entries, generated, truncated_captions)


def _parse_segments(
    segments: Sequence[Mapping[str, Any] | Sequence[Any]],
) -> tuple[list[tuple[float, float, str | None]], int]:
    """Validate the requested segments and bound their caption text."""
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)) or not segments:
        raise _flow_error("segments must be a non-empty list")
    parsed: list[tuple[float, float, str | None]] = []
    truncated_captions = 0
    for index, segment in enumerate(segments):
        start, end, text = _segment_parts(segment, index)
        if text is not None and len(text) > _CAPTION_TEXT_LIMIT:
            # A caption is burned into the picture and echoed in the receipt;
            # an unbounded string would be duplicated across both.
            text = text[:_CAPTION_TEXT_LIMIT]
            truncated_captions += 1
        parsed.append((start, end, text))
    return parsed, truncated_captions


def _validate_source_duration(source: str, parsed: list[tuple[float, float, str | None]]) -> None:
    """Refuse segments the source cannot support.

    An unmeasured source cannot be checked against the requested segments, so
    the flow refuses rather than rendering blind.
    """
    from ..engine_probe import probe as _probe_source

    try:
        duration = float(_probe_source(source).duration or 0.0)
    except (OSError, ValueError, MCPVideoError) as exc:
        raise _flow_error("could not measure the source duration") from exc
    if duration <= 0:
        raise _flow_error("could not measure the source duration; refusing to render segments that cannot be verified")
    for index, (_start, end, _text) in enumerate(parsed):
        if end > duration + _SOURCE_EOF_TOLERANCE:
            raise _flow_error(
                f"segment {index} end ({end}s) exceeds the source duration "
                f"({duration:.2f}s, tolerance {_SOURCE_EOF_TOLERANCE}s)"
            )


def video_shorts(
    input_path: str,
    segments: Sequence[Mapping[str, Any] | Sequence[Any]],
    style: str | Mapping[str, Any] | None = None,
    output_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Trim, caption, make vertical, and export selected segments in one call.

    ``segments`` accepts mappings with ``start``, ``end``, and optional ``text``
    or compact ``(start, end[, text])`` sequences.  All work stays local and
    uses the existing trim, merge, subtitle, and resize engines.
    """

    parsed, truncated_captions = _parse_segments(segments)

    from ..output_policy import output_operation

    with output_operation(overwrite):
        # The source must be validated INSIDE the operation scope. A fresh
        # `output_operation` resets the recorded-input set, so validating the
        # source first would let a later publish target this operation's own
        # input (Gate 2 P2-1: `video_shorts` could overwrite its source when
        # `overwrite=True` and `output_path == input_path`).
        source = _validate_input_path(input_path)
        caption_style, quality = _style_options(style)
        final_output = output_path or _default_output(source)

        # Fail fast on an occupied destination (same guard the final resize
        # applies) so a refusal arrives before minutes of rendering.
        _validate_output_path(final_output)

        _validate_source_duration(source, parsed)
        with tempfile.TemporaryDirectory(prefix="kinocut-shorts-") as workdir:
            trimmed_paths, assembled_path, merge_step = _assemble_segments(source, parsed, workdir)
            # Only a captioned flow needs a timeline. A render with no caption
            # text never reads a timing, so it is not blocked by a segment it
            # cannot measure.
            has_captions = any(text for (_start, _end, text) in parsed)
            segment_durations = _measured_segment_durations(trimmed_paths) if has_captions else []
            captioned_path, caption_step = _apply_captions(
                parsed,
                segment_durations,
                assembled_path,
                caption_style,
                final_output,
                workdir,
                truncated_captions,
            )

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
                    "schema_version": 2,
                    "receipt_kind": "video_shorts",
                    "steps": steps,
                },
            }
