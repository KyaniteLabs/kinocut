"""Hyperframes engine — subprocess wrappers calling the Hyperframes CLI.

No pip packages needed — Hyperframes is external (Node.js).

All file paths should be absolute. Output files are generated automatically
if no output_path is provided.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import contextlib
import html
import logging
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_COMPOSITION_FPS, DEFAULT_COMPOSITION_HEIGHT, DEFAULT_COMPOSITION_WIDTH
from .errors import (
    HyperframesNotFoundError,
    HyperframesProjectError,
    HyperframesRenderError,
    MCPVideoError,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .hyperframes_models import (
    CompositionInfo,
    CompositionsResult,
    HyperframesBlockResult,
    HyperframesJsonResult,
    HyperframesPipelineResult,
    HyperframesPreviewResult,
    HyperframesProjectResult,
    HyperframesRenderResult,
    HyperframesSnapshotResult,
    HyperframesStillResult,
    HyperframesValidationResult,
)

HYPERFRAMES_COMMAND_ENV = "MCP_VIDEO_HYPERFRAMES_COMMAND"
HYPERFRAMES_COMMAND_PREFIX = ["hyperframes"]
_HYPERFRAMES_BINARY_NAMES = ("hyperframes", "hyperframes.cmd")
_WINDOWS_COMMAND_PATH_RE = re.compile(r"^([A-Za-z]:\\.*?\.(?:bat|cmd|exe|ps1))(?=\s|$)", re.IGNORECASE)
_COMPOSITION_TAG_RE = re.compile(
    r"<[^>]*\bdata-composition-id\s*=\s*(['\"])(?P<id>.*?)\1[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_DATA_ATTR_RE = re.compile(
    r"\b(?P<name>data-[\w-]+)\s*=\s*(['\"])(?P<value>.*?)\2",
    re.IGNORECASE | re.DOTALL,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _validate_project_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise MCPVideoError(
            "Invalid name: must match ^[a-zA-Z0-9_-]+$",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return name


def _find_local_hyperframes_binary(cwd: str | Path | None) -> Path | None:
    start = Path(cwd) if cwd is not None else Path.cwd()
    try:
        start = start.resolve()
    except OSError:
        start = start.absolute()
    if start.is_file():
        start = start.parent

    for base in (start, *start.parents):
        for name in _HYPERFRAMES_BINARY_NAMES:
            candidate = base / "node_modules" / ".bin" / name
            if candidate.is_file() and (name.endswith(".cmd") or os.access(candidate, os.X_OK)):
                return candidate
    return None


def _split_configured_hyperframes_command(value: str) -> list[str]:
    configured = value.strip()
    if not configured:
        return []

    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return [str(candidate)]

    windows_match = _WINDOWS_COMMAND_PATH_RE.match(configured)
    if windows_match:
        command = windows_match.group(1)
        rest = configured[windows_match.end() :].strip()
        if not rest:
            return [command]
        return [command, *[part.strip('"') for part in shlex.split(rest, posix=False)]]

    return [part.strip('"') for part in shlex.split(configured, posix=os.name != "nt")]


def _hyperframes_command_prefix(
    cwd: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> list[str]:
    env_map = os.environ if env is None else env
    which_fn = shutil.which if which is None else which
    configured = env_map.get(HYPERFRAMES_COMMAND_ENV)
    if configured is not None:
        command = _split_configured_hyperframes_command(configured)
        if command:
            return command
        raise HyperframesNotFoundError(f"{HYPERFRAMES_COMMAND_ENV} is set but empty")

    local_binary = _find_local_hyperframes_binary(cwd)
    if local_binary is not None:
        return [str(local_binary)]

    path_binary = which_fn("hyperframes")
    if path_binary:
        return [path_binary]

    raise HyperframesNotFoundError(
        "Hyperframes CLI not found. Install a pinned Hyperframes package with "
        "node_modules/.bin/hyperframes, add hyperframes to PATH, or set "
        f"{HYPERFRAMES_COMMAND_ENV}."
    )


def _require_node() -> None:
    if shutil.which("node") is None:
        raise HyperframesNotFoundError("node not found on PATH")


def _require_hyperframes_deps(cwd: str | Path | None = None) -> None:
    """Raise a helpful error if Node.js/Hyperframes are not available."""
    _require_node()
    _hyperframes_command_prefix(cwd=cwd)


def _find_entry_point(project: Path) -> Path:
    """Locate the Hyperframes entry point (index.html or any HTML with data-composition-id)."""
    for candidate in ["index.html", "composition.html", "demo.html"]:
        if (project / candidate).is_file():
            return project / candidate
    # Fallback: any HTML file
    for f in project.iterdir():
        if f.suffix == ".html" and f.is_file():
            return f
    raise HyperframesProjectError(str(project), "Could not find entry point (no .html file)")


def _validate_project(project_path: str) -> tuple[Path, Path]:
    """Check that the project directory has the expected structure.

    Returns (project_dir, entry_point) tuple.
    """
    p = Path(project_path).resolve()
    if not p.is_dir():
        raise HyperframesProjectError(str(p), "Directory does not exist")
    entry_point = _find_entry_point(p)
    return p, entry_point


def _run_hyperframes(
    args: list[str],
    cwd: str | Path,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Run a Hyperframes command and return the CompletedProcess."""
    cmd = [*_hyperframes_command_prefix(cwd=cwd), *args]
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            # Never inherit the caller's stdin: when invoked from an MCP server
            # there is no TTY, so a stray interactive prompt would block forever.
            stdin=subprocess.DEVNULL,
            # `init` runs a network AI-skills check that the --skip-skills flag
            # does not currently disable; this env var is the supported opt-out.
            env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"},
        )
    except subprocess.TimeoutExpired:
        raise HyperframesRenderError(" ".join(cmd), -1, "Render timed out") from None
    except FileNotFoundError:
        raise HyperframesNotFoundError(f"{cmd[0]} command not found") from None


# ---------------------------------------------------------------------------
# Operation schema registry
# ---------------------------------------------------------------------------

_SCHEMA: dict[str, dict[str, Any]] = {
    "render": {
        "subcommand": "render",
        "positional": ["project_path"],
        "flags": {
            "output": "output_path",
            "fps": "fps",
            "composition": "composition",
            "quality": "quality",
            "format": "format",
            "resolution": "resolution",
            "workers": "workers",
            "crf": "crf",
            "video-bitrate": "video_bitrate",
            "variables": "variables",
            "variables-file": "variables_file",
            "max-concurrent-renders": "max_concurrent_renders",
        },
        "switches": {
            "docker": "docker",
            "hdr": "hdr",
            "sdr": "sdr",
            "gpu": "gpu",
            "browser-gpu": "browser_gpu",
            "no-browser-gpu": "no_browser_gpu",
            "quiet": "quiet",
            "strict": "strict",
            "strict-all": "strict_all",
            "strict-variables": "strict_variables",
        },
        "timeout": 600,
    },
    "compositions": {
        "subcommand": "compositions",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
    "snapshot": {
        "subcommand": "snapshot",
        "positional": ["project_path"],
        "flags": {
            "frames": "frames",
            "at": "at_csv",
            "timeout": "timeout_ms",
            "variables": "variables",
            "variables-file": "variables_file",
        },
        "timeout": 120,
    },
    "inspect": {
        "subcommand": "inspect",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "flags": {
            "samples": "samples",
            "at": "at_csv",
            "tolerance": "tolerance",
            "timeout": "timeout_ms",
            "max-issues": "max_issues",
        },
        "switches": {
            "strict": "strict",
            "collapse-static": "collapse_static",
            "no-collapse-static": "no_collapse_static",
        },
        "timeout": 120,
    },
    "info": {
        "subcommand": "info",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
    "catalog": {
        "subcommand": "catalog",
        "fixed": ["--json"],
        "flags": {
            "type": "item_type",
            "tag": "tag",
        },
        "cwd_key": None,
        "timeout": 60,
    },
    "capture": {
        "subcommand": "capture",
        "positional": ["url"],
        "fixed": ["--json"],
        "flags": {
            "output": "output",
            "max-screenshots": "max_screenshots",
            "timeout": "timeout_ms",
        },
        "switches": {
            "skip-assets": "skip_assets",
        },
        "cwd_key": None,
        "timeout": 180,
    },
    "transcribe": {
        "subcommand": "transcribe",
        "positional": ["input_path"],
        "fixed": ["--json"],
        "flags": {
            "dir": "project_path",
            "model": "model",
            "language": "language",
        },
        "cwd_key": None,
        "timeout": 600,
    },
    "tts": {
        "subcommand": "tts",
        "optional_positional": ["text_or_file"],
        "fixed": ["--json"],
        "flags": {
            "output": "output_path",
            "voice": "voice",
            "speed": "speed",
            "lang": "language",
        },
        "switches": {
            "list": "list_voices",
        },
        "cwd_key": None,
        "timeout": 600,
    },
    "remove-background": {
        "subcommand": "remove-background",
        "positional": ["input_path"],
        "fixed": ["--json"],
        "flags": {
            "output": "output_path",
            "background-output": "background_output_path",
            "device": "device",
            "quality": "quality",
        },
        "switches": {
            "info": "info",
        },
        "cwd_key": None,
        "timeout": 900,
    },
    "doctor": {
        "subcommand": "doctor",
        "fixed": ["--json"],
        "cwd_key": None,
        "timeout": 60,
    },
    "benchmark": {
        "subcommand": "benchmark",
        "positional": ["project_path"],
        "flags": {
            "output": "output_path",
            "runs": "runs",
        },
        "switches": {
            "json": "json_output",
        },
        "timeout": 900,
    },
    "add": {
        "subcommand": "add",
        "positional": ["block_name"],
        "flags": {
            "dir": "project_path",
        },
        "switches": {
            "no-clipboard": "no_clipboard",
        },
        "fixed": ["--json"],
        "timeout": 60,
    },
    "init": {
        "subcommand": "init",
        "positional": ["name"],
        "flags": {
            "example": "template",
            "video": "video",
            "audio": "audio",
            "model": "model",
            "language": "language",
            "resolution": "resolution",
        },
        "switches": {
            "tailwind": "tailwind",
            # Opt-in: emit the skip flag only when the caller requests it via
            # create_project(skip_transcribe=True).
            "skip-transcribe": "skip_transcribe",
        },
        # `init` prompts interactively by default and can implicitly launch
        # Whisper; always pass --non-interactive so the MCP subprocess scaffolds
        # a project without ever blocking on input. --skip-transcribe is opt-in
        # above, so the public default (skip_transcribe=False) omits it.
        "fixed": ["--non-interactive", "--skip-skills"],
        "cwd_key": "output_dir",
        "timeout": 120,
    },
    "lint": {
        "subcommand": "lint",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
}


def _hyperframes_op(
    operation: str,
    **kwargs: Any,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run a hyperframes subcommand from the schema registry.

    Returns (completed_process, cwd_path).
    """
    spec = _SCHEMA.get(operation)
    if spec is None:
        raise MCPVideoError(
            f"Unknown hyperframes operation: {operation}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    _require_node()

    cwd_key = spec.get("cwd_key", "project_path")
    if cwd_key is None:
        cwd = Path(kwargs.get("cwd") or os.getcwd()).resolve()
    else:
        cwd_val = kwargs.get(cwd_key)
        if cwd_val is None:
            raise MCPVideoError(
                f"Missing required parameter: {cwd_key}",
                error_type="validation_error",
                code="invalid_parameter",
            )

        if cwd_key == "project_path":
            cwd, _entry_point = _validate_project(cwd_val)
            kwargs[cwd_key] = str(cwd)
        else:
            cwd = Path(cwd_val).resolve()
            kwargs[cwd_key] = str(cwd)

    _require_hyperframes_deps(cwd=cwd)

    args: list[str] = [spec["subcommand"]]

    for pos_key in spec.get("positional", []):
        val = kwargs.get(pos_key)
        if val is None:
            raise MCPVideoError(
                f"Missing required parameter: {pos_key}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        args.append(str(val))

    for pos_key in spec.get("optional_positional", []):
        val = kwargs.get(pos_key)
        if val:
            args.append(str(val))

    for flag, kw_key in spec.get("flags", {}).items():
        val = kwargs.get(kw_key)
        if val is not None:
            args.extend([f"--{flag}", _format_cli_value(val)])

    for flag, kw_key in spec.get("switches", {}).items():
        if kwargs.get(kw_key):
            args.append(f"--{flag}")

    for item in spec.get("fixed", []):
        args.append(item)

    for flag, compute in spec.get("computed", {}).items():
        args.extend([f"--{flag}", _format_cli_value(compute(kwargs))])

    result = _run_hyperframes(args, cwd=cwd, timeout=spec.get("timeout", 600))
    if result.returncode != 0:
        raise HyperframesRenderError(" ".join(args), result.returncode, result.stderr)

    return result, cwd


def _format_cli_value(value: Any) -> str:
    """Format Hyperframes CLI flag values without introducing false precision."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


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
# Public API
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


def render(
    project_path: str,
    output_path: str | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
    composition: str | None = None,
    quality: str | None = None,
    format: str | None = None,
    resolution: str | None = None,
    workers: str | int | None = None,
    crf: int | None = None,
    video_bitrate: str | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
    docker: bool = False,
    hdr: bool = False,
    sdr: bool = False,
    gpu: bool = False,
    browser_gpu: bool = False,
    no_browser_gpu: bool = False,
    quiet: bool = False,
    strict: bool = False,
    strict_all: bool = False,
    max_concurrent_renders: int | None = None,
    strict_variables: bool = False,
) -> HyperframesRenderResult:
    """Render a Hyperframes composition to video."""
    if output_path is None:
        output_path = _default_render_output(project_path, format)

    effective_resolution = _resolve_render_resolution(width, height, resolution)
    variables_file = _validate_variables_file(variables_file)

    start_time = time.time()
    _result, _project = _hyperframes_op(
        "render",
        project_path=project_path,
        output_path=output_path,
        fps=fps,
        composition=composition,
        quality=quality,
        format=format,
        resolution=effective_resolution,
        workers=workers,
        crf=crf,
        video_bitrate=video_bitrate,
        variables=variables,
        variables_file=variables_file,
        docker=docker,
        hdr=hdr,
        sdr=sdr,
        gpu=gpu,
        browser_gpu=browser_gpu,
        no_browser_gpu=no_browser_gpu,
        quiet=quiet,
        strict=strict,
        strict_all=strict_all,
        max_concurrent_renders=max_concurrent_renders,
        strict_variables=strict_variables,
    )

    render_time = round(time.time() - start_time, 1)
    try:
        size = os.path.getsize(output_path) if os.path.isfile(output_path) else None
        size_mb = round(size / (1024 * 1024), 2) if size is not None else None
    except OSError:
        size_mb = None

    reported_resolution = effective_resolution
    if width and height:
        reported_resolution = f"{width}x{height}"

    if not _render_output_exists(output_path, format):
        return HyperframesRenderResult(
            output_path=output_path,
            codec=format or "h264",
            size_mb=None,
            render_time=render_time,
            resolution=reported_resolution,
            success=False,
        )

    return HyperframesRenderResult(
        output_path=output_path,
        codec=format or "h264",
        size_mb=size_mb,
        render_time=render_time,
        resolution=reported_resolution,
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


def preview(
    project_path: str,
    port: int = 3002,
    startup_timeout: int = 10,
) -> HyperframesPreviewResult:
    """Launch Hyperframes preview studio (non-blocking)."""
    if port < 1024 or port > 65535:
        raise HyperframesProjectError(str(project_path), "Preview port must be between 1024 and 65535")
    _require_node()
    project, _entry_point = _validate_project(project_path)
    _require_hyperframes_deps(cwd=project)

    cmd = [*_hyperframes_command_prefix(cwd=project), "preview", str(project), "--port", str(port)]
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(project),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )

    time.sleep(min(startup_timeout, 2))
    if proc.poll() is not None:
        raise HyperframesProjectError(str(project), "Hyperframes preview exited immediately")

    return HyperframesPreviewResult(
        url=f"http://localhost:{port}",
        port=port,
        project_path=str(project),
        pid=proc.pid,
    )


def still(
    project_path: str,
    output_path: str | None = None,
    frame: int = 0,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> HyperframesStillResult:
    """Render a single frame from a Hyperframes composition.

    Hyperframes writes snapshot PNGs into the project ``snapshots/``
    directory and does not accept an output file flag. Return the actual
    generated frame path instead of echoing a requested-but-unwritten path.
    """
    seconds = frame / 30.0
    snap = snapshot(project_path, at=[seconds], frames=1, variables=variables, variables_file=variables_file)
    actual_output = snap.frame_paths[0] if snap.frame_paths else output_path or ""

    return HyperframesStillResult(
        output_path=actual_output,
        frame=frame,
    )


def snapshot(
    project_path: str,
    frames: int = 5,
    at: list[float] | None = None,
    timeout_ms: int | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> HyperframesSnapshotResult:
    """Capture key frames as PNG screenshots for visual verification."""
    _require_node()
    project, _entry_point = _validate_project(project_path)
    snapshot_dir = project / "snapshots"
    before = set(snapshot_dir.glob("*.png")) if snapshot_dir.is_dir() else set()
    at_csv = _csv(at)
    variables_file = _validate_variables_file(variables_file)
    _hyperframes_op(
        "snapshot",
        project_path=project_path,
        frames=frames if at_csv is None else None,
        at_csv=at_csv,
        timeout_ms=timeout_ms,
        variables=variables,
        variables_file=variables_file,
    )
    frame_paths = _snapshot_pngs(project, before)
    return HyperframesSnapshotResult(
        frame_paths=frame_paths,
        output_dir=str(snapshot_dir),
        frames=frames,
        at=at or [],
    )


def inspect(
    project_path: str,
    samples: int = 9,
    at: list[float] | None = None,
    tolerance: int = 2,
    timeout_ms: int | None = None,
    max_issues: int = 80,
    collapse_static: bool = False,
    no_collapse_static: bool = False,
    strict: bool = False,
) -> HyperframesJsonResult:
    """Inspect rendered layout for text and container overflow."""
    result, _project = _hyperframes_op(
        "inspect",
        project_path=project_path,
        samples=samples,
        at_csv=_csv(at),
        tolerance=tolerance,
        timeout_ms=timeout_ms,
        max_issues=max_issues,
        collapse_static=collapse_static,
        no_collapse_static=no_collapse_static,
        strict=strict,
    )
    return _json_result("inspect", result)


def info(project_path: str) -> HyperframesJsonResult:
    """Return Hyperframes project metadata."""
    result, _project = _hyperframes_op("info", project_path=project_path)
    return _json_result("info", result)


def catalog(item_type: str | None = None, tag: str | None = None) -> HyperframesJsonResult:
    """Browse Hyperframes catalog blocks/components."""
    result, _cwd = _hyperframes_op("catalog", item_type=item_type, tag=tag)
    return _json_result("catalog", result)


def capture(
    url: str,
    output: str | None = None,
    skip_assets: bool = False,
    max_screenshots: int | None = None,
    timeout_ms: int | None = None,
) -> HyperframesJsonResult:
    """Capture a website as editable Hyperframes components."""
    result, _cwd = _hyperframes_op(
        "capture",
        url=url,
        output=output,
        skip_assets=skip_assets,
        max_screenshots=max_screenshots,
        timeout_ms=timeout_ms,
    )
    return _json_result("capture", result)


def transcribe(
    input_path: str,
    project_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
) -> HyperframesJsonResult:
    """Transcribe audio/video to word-level timestamps or import transcript files."""
    result, _cwd = _hyperframes_op(
        "transcribe",
        input_path=input_path,
        project_path=project_path,
        model=model,
        language=language,
    )
    return _json_result("transcribe", result)


def tts(
    text_or_file: str | None = None,
    output_path: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
    language: str | None = None,
    list_voices: bool = False,
) -> HyperframesJsonResult:
    """Generate speech audio from text using Hyperframes local TTS."""
    if not list_voices and not text_or_file:
        raise MCPVideoError(
            "text_or_file is required unless list_voices is true",
            error_type="validation_error",
            code="invalid_parameter",
        )
    result, _cwd = _hyperframes_op(
        "tts",
        text_or_file=text_or_file,
        output_path=output_path,
        voice=voice,
        speed=speed,
        language=language,
        list_voices=list_voices,
    )
    return _json_result("tts", result)


def remove_background(
    input_path: str,
    output_path: str | None = None,
    background_output_path: str | None = None,
    device: str = "auto",
    quality: str = "balanced",
    info: bool = False,
) -> HyperframesJsonResult:
    """Remove a video/image background with Hyperframes local AI."""
    result, _cwd = _hyperframes_op(
        "remove-background",
        input_path=input_path,
        output_path=output_path,
        background_output_path=background_output_path,
        device=device,
        quality=quality,
        info=info,
    )
    return _json_result("remove-background", result)


def doctor() -> HyperframesJsonResult:
    """Run Hyperframes environment diagnostics."""
    result, _cwd = _hyperframes_op("doctor")
    return _json_result("doctor", result)


def benchmark(
    project_path: str,
    output_path: str | None = None,
    runs: int | None = None,
    json_output: bool = True,
) -> HyperframesJsonResult:
    """Benchmark Hyperframes render speed and output size."""
    result, _project = _hyperframes_op(
        "benchmark",
        project_path=project_path,
        output_path=output_path,
        runs=runs,
        json_output=json_output,
    )
    return _json_result("benchmark", result)


def create_project(
    name: str,
    output_dir: str | None = None,
    template: str = "blank",
    video: str | None = None,
    audio: str | None = None,
    skip_transcribe: bool = False,
    model: str | None = None,
    language: str | None = None,
    tailwind: bool = False,
    resolution: str | None = None,
) -> HyperframesProjectResult:
    """Scaffold a new Hyperframes project."""
    name = _validate_project_name(name)
    if output_dir is None:
        output_dir = os.getcwd()
    output_dir = _validate_output_path(output_dir)
    project_dir = Path(output_dir) / name
    _validate_output_path(str(project_dir))

    _require_hyperframes_deps(cwd=output_dir)

    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"Warning: Project directory already exists and is not empty — files will be overwritten: {project_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)

    _hyperframes_op(
        "init",
        name=name,
        template=template,
        output_dir=output_dir,
        video=video,
        audio=audio,
        skip_transcribe=skip_transcribe,
        model=model,
        language=language,
        tailwind=tailwind,
        resolution=resolution,
    )

    # Discover created files
    files: list[str] = []
    if project_dir.exists():
        for f in project_dir.rglob("*"):
            if f.is_file():
                files.append(str(f.relative_to(project_dir)))

    return HyperframesProjectResult(
        project_path=str(project_dir),
        template=template,
        files=files,
    )


def validate(
    project_path: str,
) -> HyperframesValidationResult:
    """Validate a Hyperframes project for rendering readiness."""
    issues: list[str] = []
    warnings: list[str] = []

    p = Path(project_path).resolve()

    if not p.is_dir():
        issues.append("Project directory does not exist")
        return HyperframesValidationResult(
            valid=False,
            issues=issues,
            warnings=warnings,
            project_path=str(p),
        )

    try:
        _find_entry_point(p)
    except HyperframesProjectError:
        issues.append("No HTML entry point found (expected index.html)")

    # Check Node.js/Hyperframes
    if shutil.which("node") is None:
        issues.append("Node.js not found on PATH")
    try:
        _hyperframes_command_prefix(cwd=p)
    except HyperframesNotFoundError as e:
        issues.append(f"Hyperframes CLI not found: {e}")

    # Run hyperframes lint if deps are available
    if shutil.which("node") is not None and not any("Hyperframes CLI not found" in issue for issue in issues):
        try:
            result = _run_hyperframes(["lint", str(p), "--json"], cwd=p, timeout=60)
            if result.returncode != 0:
                try:
                    lint_data = json.loads(result.stdout)
                    for finding in lint_data.get("errors", []):
                        issues.append(f"lint: {finding}")
                    for finding in lint_data.get("warnings", []):
                        warnings.append(f"lint: {finding}")
                except json.JSONDecodeError:
                    issues.append(f"lint failed: {result.stderr[:200]}")
        except Exception as e:
            warnings.append(f"Could not run hyperframes lint: {e}")

    valid = len(issues) == 0

    return HyperframesValidationResult(
        valid=valid,
        issues=issues,
        warnings=warnings,
        project_path=str(p),
    )


def add_block(
    project_path: str,
    block_name: str,
    no_clipboard: bool = False,
) -> HyperframesBlockResult:
    """Install a block from the Hyperframes catalog."""
    result, project = _hyperframes_op(
        "add",
        project_path=project_path,
        block_name=block_name,
        no_clipboard=no_clipboard,
    )

    files_added: list[str] = []
    try:
        add_data = json.loads(result.stdout)
        files_added = add_data.get("files", [])
    except json.JSONDecodeError:
        pass

    return HyperframesBlockResult(
        project_path=str(project),
        block_name=block_name,
        files_added=files_added,
    )


def render_and_post(
    project_path: str,
    post_process: list[dict[str, Any]],
    output_path: str | None = None,
) -> HyperframesPipelineResult:
    """Render a Hyperframes composition, then apply mcp-video post-processing."""
    # Step 1: Render with Hyperframes
    render_result = render(project_path)
    hyperframes_output = render_result.output_path
    if not render_result.success:
        raise HyperframesRenderError(
            "hyperframes render",
            0,
            f"Render completed but output artifact was not created: {hyperframes_output}",
        )

    # Step 2: Post-process with mcp-video engine
    op_map = _post_process_ops()

    operations: list[str] = []
    current_input = hyperframes_output

    for i, op in enumerate(post_process):
        op_type = op.get("op", op.get("type", ""))
        params = op.get("params", {})
        is_last = i == len(post_process) - 1

        if op_type not in op_map:
            raise MCPVideoError(
                f"Unknown post-processing operation: '{op_type}'. Valid operations: {', '.join(op_map)}",
                error_type="validation_error",
                code="invalid_parameter",
            )

        step_output = output_path if is_last else None
        result = op_map[op_type](current_input, output_path=step_output, **params)
        current_input = result.output_path
        operations.append(op_type)

    return HyperframesPipelineResult(
        hyperframes_output=hyperframes_output,
        final_output=current_input,
        operations=operations,
    )
