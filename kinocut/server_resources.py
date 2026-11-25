"""MCP resource registrations for the Kinocut server (mcp-video:// URIs are compatibility aliases)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

from mcp.server.fastmcp.resources import ResourceTemplate

from .errors import MCPVideoError
from .server_app import _error_result, mcp

_SCHEME_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]{1,}://")
_TEMPLATE_PARAM_RE = re.compile(r"\{([^{}]+)\}")


class _MultiSegmentResourceTemplate(ResourceTemplate):
    """ResourceTemplate allowing ``{path}`` to span directory separators."""

    def matches(self, uri: str) -> dict[str, Any] | None:
        parts: list[str] = []
        last = 0
        for match in _TEMPLATE_PARAM_RE.finditer(self.uri_template):
            parts.append(re.escape(self.uri_template[last : match.start()]))
            name = match.group(1)
            expr = ".+" if name == "path" else "[^/]+"
            parts.append(f"(?P<{name}>{expr})")
            last = match.end()
        parts.append(re.escape(self.uri_template[last:]))
        matched = re.fullmatch("".join(parts), uri)
        if matched:
            return matched.groupdict()
        return None


def _register_path_resource(uri_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a file-backed MCP resource template that accepts multi-segment paths."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        template = _MultiSegmentResourceTemplate.from_function(
            fn,
            uri_template=uri_template,
            name=fn.__name__,
            description=fn.__doc__ or "",
        )
        mcp._resource_manager._templates[template.uri_template] = template
        return fn

    return decorator


def _decode_resource_path(raw_path: str) -> str:
    """Decode one percent-encoding layer and enforce traversal/control/scheme guards."""
    if not isinstance(raw_path, str) or not raw_path:
        raise MCPVideoError(
            "Resource path must be non-empty.",
            error_type="validation_error",
            code="unsafe_path",
        )
    if "\x00" in raw_path or any(ord(c) < 32 for c in raw_path):
        raise MCPVideoError(
            "Resource path cannot contain control characters.",
            error_type="validation_error",
            code="unsafe_path",
        )
    if ".." in re.split(r"[\\/]+", raw_path):
        raise MCPVideoError(
            "Directory traversal is not allowed in resource paths.",
            error_type="validation_error",
            code="unsafe_path",
        )
    decoded = unquote(raw_path)
    if not decoded or "\x00" in decoded or any(ord(c) < 32 for c in decoded):
        raise MCPVideoError(
            "Decoded resource path is empty or contains control characters.",
            error_type="validation_error",
            code="unsafe_path",
        )
    if ".." in re.split(r"[\\/]+", decoded):
        raise MCPVideoError(
            "Directory traversal is not allowed in resource paths.",
            error_type="validation_error",
            code="unsafe_path",
        )
    if _SCHEME_PREFIX_RE.match(decoded):
        raise MCPVideoError(
            "URL schemes are not allowed in file-backed resource paths.",
            error_type="validation_error",
            code="unsafe_path",
        )
    return decoded


def _probe(path: str):
    # Deferred: keeps heavy engine imports off the server startup path while
    # the resource handlers themselves stay registered from process start.
    from .engine_probe import probe

    return probe(_decode_resource_path(path))


@_register_path_resource("mcp-video://video/{path}/info")
def video_info_resource(path: str) -> str:
    """Get metadata about a video file (duration, resolution, codec, etc.)."""
    try:
        info = _probe(path)
        return info.model_dump_json(indent=2)
    except MCPVideoError as e:
        return json.dumps(_error_result(e), indent=2)


@_register_path_resource("mcp-video://video/{path}/preview")
def video_preview_resource(path: str) -> str:
    """Get a text storyboard description (key frame timestamps)."""
    try:
        info = _probe(path)
        frames = []
        dur = info.duration
        count = 8
        for i in range(count):
            ts = dur * (i + 1) / (count + 1)
            frames.append(f"Frame {i + 1}: {ts:.1f}s")
        return "\n".join(frames)
    except MCPVideoError as e:
        return json.dumps(_error_result(e), indent=2)


@_register_path_resource("mcp-video://video/{path}/audio")
def video_audio_resource(path: str) -> str:
    """Extract and describe the audio track of a video."""
    try:
        info = _probe(path)
        if info.audio_codec:
            return (
                f"Audio codec: {info.audio_codec}\n"
                f"Sample rate: {info.audio_sample_rate} Hz\n"
                f"Duration: {info.duration:.1f}s"
            )
        return "No audio track found."
    except MCPVideoError as e:
        return json.dumps(_error_result(e), indent=2)


@mcp.resource("mcp-video://templates")
def templates_resource() -> str:
    """List available editing templates (aspect ratios, quality presets)."""
    from .models import ASPECT_RATIOS, QUALITY_PRESETS

    data = {
        "aspect_ratios": {k: f"{v[0]}x{v[1]}" for k, v in ASPECT_RATIOS.items()},
        "quality_presets": {
            k: f"CRF {v['crf']}, preset={v['preset']}, max_height={v['max_height']}" for k, v in QUALITY_PRESETS.items()
        },
        "transition_types": ["fade", "dissolve", "wipe-left", "wipe-right", "wipe-up", "wipe-down"],
        "export_formats": ["mp4", "webm", "gif", "mov"],
        "text_positions": [
            "top-left",
            "top-center",
            "top-right",
            "center-left",
            "center",
            "center-right",
            "bottom-left",
            "bottom-center",
            "bottom-right",
        ],
    }
    return json.dumps(data, indent=2)
