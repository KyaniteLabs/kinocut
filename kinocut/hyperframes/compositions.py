"""Read Hyperframes composition metadata from the CLI and project markup."""

from __future__ import annotations

import contextlib
import html
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_COMPOSITION_FPS, DEFAULT_COMPOSITION_HEIGHT, DEFAULT_COMPOSITION_WIDTH
from .models import CompositionInfo, CompositionsResult
from .runner import _hyperframes_op

logger = logging.getLogger(__name__)


_COMPOSITION_TAG_RE = re.compile(
    r"<[^>]*\bdata-composition-id\s*=\s*(['\"])(?P<id>.*?)\1[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_DATA_ATTR_RE = re.compile(
    r"\b(?P<name>data-[\w-]+)\s*=\s*(['\"])(?P<value>.*?)\2",
    re.IGNORECASE | re.DOTALL,
)


def _parse_compositions_output(stdout: str) -> list[dict[str, Any]]:
    """Parse compositions from hyperframes CLI output (JSON or text format)."""
    # Try JSON first
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("compositions", [data])
    except json.JSONDecodeError:
        pass

    # Fallback: simple regex for text output
    comps = []
    pattern = re.compile(
        r"^(\S+)\s+(\d+)\s+(\d+)x(\d+)\s+(\d+)\s+\(.*\)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(stdout):
        comps.append(
            {
                "id": m.group(1),
                "fps": int(m.group(2)),
                "width": int(m.group(3)),
                "height": int(m.group(4)),
                "durationInFrames": int(m.group(5)),
                "defaultProps": {},
            }
        )
    return comps


def _composition_html_metadata(project: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for html_path in project.rglob("*.html"):
        if "node_modules" in html_path.parts:
            continue
        try:
            content = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping Hyperframes composition metadata file %s: %s", html_path, e)
            continue
        for tag_match in _COMPOSITION_TAG_RE.finditer(content):
            attrs = {
                attr.group("name").lower(): html.unescape(attr.group("value").strip())
                for attr in _DATA_ATTR_RE.finditer(tag_match.group(0))
            }
            comp_id = attrs.get("data-composition-id") or html.unescape(tag_match.group("id").strip())
            if not comp_id:
                continue

            item: dict[str, Any] = {}
            if duration := attrs.get("data-duration") or attrs.get("data-duration-seconds"):
                item["_html_duration"] = duration
            if fps := attrs.get("data-fps"):
                item["_html_fps"] = fps
            if width := _coerce_positive_int(attrs.get("data-width")):
                item["_html_width"] = width
            if height := _coerce_positive_int(attrs.get("data-height")):
                item["_html_height"] = height
            if item:
                metadata[comp_id] = {**metadata.get(comp_id, {}), **item}
    return metadata


def _coerce_float(value: Any) -> float | None:
    with contextlib.suppress(TypeError, ValueError):
        return float(value)
    return None


def _coerce_positive_float(value: Any) -> float | None:
    number = _coerce_float(value)
    if number and number > 0:
        return number
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, str):
        value = value.strip()
        if value.lower().endswith("px"):
            value = value[:-2].strip()
    number = _coerce_float(value)
    if number is None or not math.isfinite(number):
        return None
    try:
        integer = int(number)
    except (OverflowError, ValueError):
        return None
    if integer > 0 and float(integer) == float(number):
        return integer
    return None


def _effective_composition_fps(data: dict[str, Any]) -> float:
    return (
        _coerce_positive_float(data.get("fps"))
        or _coerce_positive_float(data.get("_html_fps"))
        or DEFAULT_COMPOSITION_FPS
    )


def _composition_duration_frames(data: dict[str, Any]) -> int:
    fps = _effective_composition_fps(data)
    frame_value = data.get("durationInFrames", data.get("duration_in_frames"))
    frames = _coerce_float(frame_value)
    if frames and frames > 0:
        return round(frames)

    seconds = _coerce_float(data.get("durationInSeconds", data.get("duration")))
    if not seconds:
        seconds = _coerce_float(data.get("_html_duration"))
    if seconds and seconds > 0:
        return round(seconds * fps)

    return 0


def compositions(
    project_path: str,
) -> CompositionsResult:
    """List compositions in a Hyperframes project."""
    result, project = _hyperframes_op("compositions", project_path=project_path)

    raw = _parse_compositions_output(result.stdout)
    html_metadata = _composition_html_metadata(project)

    comp_list = []
    for c in raw:
        comp_id = str(c.get("id", c.get("compositionId", "")))
        merged = {**html_metadata.get(comp_id, {}), **c}
        comp_list.append(
            CompositionInfo(
                id=comp_id,
                width=merged.get("width", merged.get("_html_width", DEFAULT_COMPOSITION_WIDTH)),
                height=merged.get("height", merged.get("_html_height", DEFAULT_COMPOSITION_HEIGHT)),
                fps=_effective_composition_fps(merged),
                duration_in_frames=_composition_duration_frames(merged),
                default_props=merged.get("defaultProps", {}),
            )
        )

    return CompositionsResult(
        compositions=comp_list,
        project_path=str(project),
    )


# ---------------------------------------------------------------------------
# Frames & inspection
# ---------------------------------------------------------------------------
