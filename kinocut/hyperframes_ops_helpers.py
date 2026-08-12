"""Private helpers for hyperframes_ops (size split; keep ops ≤800 LOC)."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path
from .hyperframes_models import HyperframesJsonResult

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _validate_variables_file(path: str | os.PathLike[str] | None) -> str | None:
    """Validate optional runtime-data files before forwarding them to Hyperframes."""
    if path is None:
        return None
    return _validate_input_path(str(path))


def _post_process_ops() -> dict[str, Callable]:
    """Return the post-processing operation registry for render_and_post."""
    from . import engine as _video_engine

    return {
        "resize": _video_engine.resize,
        "convert": _video_engine.convert,
        "add_audio": _video_engine.add_audio,
        "normalize_audio": _video_engine.normalize_audio,
        "add_text": _video_engine.add_text,
        "fade": _video_engine.fade,
        "watermark": _video_engine.watermark,
    }


def _parse_json_stdout(stdout: str) -> dict[str, Any] | list[Any] | str:
    """Parse Hyperframes JSON output, preserving text when a command is human-only."""
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _csv(values: list[float] | list[str] | None) -> str | None:
    if not values:
        return None
    return ",".join(str(v) for v in values)


def _snapshot_pngs(project: Path, before: set[Path]) -> list[str]:
    snapshot_dir = project / "snapshots"
    if not snapshot_dir.is_dir():
        return []
    after = set(snapshot_dir.glob("*.png"))
    created = after - before
    paths = sorted(created or after)
    return [str(path) for path in paths]


def _json_result(command: str, result: subprocess.CompletedProcess[str]) -> HyperframesJsonResult:
    return HyperframesJsonResult(command=command, data=_parse_json_stdout(result.stdout), stdout=result.stdout)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _resolution_from_dimensions(width: int | None, height: int | None) -> str | None:
    """Return the Hyperframes resolution preset matching legacy width/height args."""
    match (width, height):
        case (1920, 1080):
            return "landscape"
        case (1080, 1920):
            return "portrait"
        case (3840, 2160):
            return "landscape-4k"
        case (2160, 3840):
            return "portrait-4k"
        case _:
            return None


def _canonical_resolution(value: str | None) -> str | None:
    """Normalize Hyperframes resolution aliases to canonical presets."""
    match value:
        case None:
            return None
        case "1080p":
            return "landscape"
        case "4k" | "uhd":
            return "landscape-4k"
        case _:
            return value


def _default_render_output(project_path: str, output_format: str | None) -> str:
    """Return a format-appropriate default render artifact path."""
    os.makedirs("out", exist_ok=True)
    name = Path(project_path).name
    match output_format:
        case "png-sequence":
            return os.path.join("out", f"{name}_frames")
        case "webm" | "mov" | "mp4":
            return os.path.join("out", f"{name}.{output_format}")
        case _:
            return os.path.join("out", f"{name}.mp4")


def _render_output_exists(output_path: str, output_format: str | None) -> bool:
    """Return true when the expected Hyperframes artifact exists."""
    if output_format == "png-sequence":
        output_dir = Path(output_path)
        return output_dir.is_dir() and any(output_dir.glob("*.png"))
    return os.path.isfile(output_path)


def _resolve_render_resolution(width: int | None, height: int | None, resolution: str | None) -> str | None:
    """Return the effective Hyperframes resolution without silently ignoring dimensions."""
    if (width is None) ^ (height is None):
        raise MCPVideoError(
            "width and height must be provided together",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if width is None and height is None:
        return resolution

    dimension_resolution = _resolution_from_dimensions(width, height)
    if dimension_resolution is None:
        raise MCPVideoError(
            "Hyperframes render only supports width/height pairs that map to --resolution presets: "
            "1920x1080, 1080x1920, 3840x2160, or 2160x3840. Use resolution=... instead of arbitrary dimensions.",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if resolution is not None and _canonical_resolution(resolution) != dimension_resolution:
        raise MCPVideoError(
            f"width/height {width}x{height} conflicts with resolution '{resolution}'",
            error_type="validation_error",
            code="invalid_parameter",
        )

    return resolution or dimension_resolution
