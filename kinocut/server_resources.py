"""MCP resource registrations for the mcp-video server."""

from __future__ import annotations

import json

from .engine import probe
from .errors import MCPVideoError
from .server_app import _error_result, mcp


@mcp.resource("mcp-video://video/{path}/info")
def video_info_resource(path: str) -> str:
    """Get metadata about a video file (duration, resolution, codec, etc.)."""
    try:
        info = probe(path)
        return info.model_dump_json(indent=2)
    except MCPVideoError as e:
        return json.dumps(_error_result(e), indent=2)


@mcp.resource("mcp-video://video/{path}/preview")
def video_preview_resource(path: str) -> str:
    """Get a text storyboard description (key frame timestamps)."""
    try:
        info = probe(path)
        frames = []
        dur = info.duration
        count = 8
        for i in range(count):
            ts = dur * (i + 1) / (count + 1)
            frames.append(f"Frame {i + 1}: {ts:.1f}s")
        return "\n".join(frames)
    except MCPVideoError as e:
        return json.dumps(_error_result(e), indent=2)


@mcp.resource("mcp-video://video/{path}/audio")
def video_audio_resource(path: str) -> str:
    """Extract and describe the audio track of a video."""
    try:
        info = probe(path)
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
