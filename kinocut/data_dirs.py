"""Where Kinocut keeps downloaded models, fonts and CRUSH shaders.

KINOCUT_DATA_DIR (for example a host plugin data directory) moves all of it.
Without it the pre-rename home paths stay in use so existing installs keep
their caches.
"""

from __future__ import annotations

import os
from pathlib import Path


def _override() -> Path | None:
    raw = os.environ.get("KINOCUT_DATA_DIR", "").strip()
    return Path(raw).expanduser() if raw else None


def crush_home() -> Path:
    """Root that holds crush-js/src (legacy: ~/.mcp-video)."""
    return _override() or Path.home() / ".mcp-video"


def cache_home() -> Path:
    """Root for downloaded models and fonts (legacy: ~/.cache/mcp-video)."""
    override = _override()
    return override / "cache" if override else Path.home() / ".cache" / "mcp-video"
