"""Shared version helpers for workflow artifacts.

The plan artifact (``planner``) and the render receipt (``executor``) must both
report the identical ``versions`` object (tool + FFmpeg). This module owns the
single source of truth so the two artifacts can never drift apart.
"""

from __future__ import annotations

import re
import subprocess

from .. import __version__ as _MCP_VIDEO_VERSION

# Single source of truth for the determinism caveat every workflow artifact
# (plan + render receipt) records, so the two can never drift apart.
RENDER_DETERMINISM_SCOPE = "spec/input/output hashes are deterministic; rendered bytes may vary across FFmpeg builds"

_ffmpeg_version_cache: str | None = None
_ffmpeg_version_probed = False


def mcp_video_version() -> str:
    """Return the live installed mcp-video package version."""
    return _MCP_VIDEO_VERSION


def ffmpeg_version() -> str | None:
    """Probe the runtime FFmpeg version token (e.g. ``7.1.1``), memoized."""
    global _ffmpeg_version_cache, _ffmpeg_version_probed
    if _ffmpeg_version_probed:
        return _ffmpeg_version_cache
    _ffmpeg_version_probed = True
    command = ["ffmpeg", "-version"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        _ffmpeg_version_cache = None
        return None
    first_line = (result.stdout or result.stderr or "").splitlines()[:1]
    match = re.search(r"ffmpeg version (\S+)", first_line[0], re.IGNORECASE) if first_line else None
    _ffmpeg_version_cache = match.group(1) if match else None
    return _ffmpeg_version_cache


def versions() -> dict[str, str | None]:
    """Return the shared ``{mcp_video, ffmpeg}`` versions object for artifacts."""
    return {"mcp_video": mcp_video_version(), "ffmpeg": ffmpeg_version()}
