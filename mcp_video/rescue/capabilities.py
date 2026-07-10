"""Side-effect-free discovery of local rescue executors."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from collections.abc import Callable
from functools import lru_cache
from importlib import metadata
from typing import Any

from ..workflow._versions import ffmpeg_version


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=4)
def _ffmpeg_filters(executable: str) -> frozenset[str]:
    try:
        result = subprocess.run(  # noqa: S603
            [executable, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if result.returncode != 0:
        return frozenset()

    filters: set[str] = set()
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 2 and columns[0].strip(".").isalpha():
            filters.add(columns[1])
    return frozenset(filters)


def snapshot_capabilities(
    *,
    which: Callable[[str], str | None] = shutil.which,
    find_spec: Callable[[str], Any] | None = None,
    package_version: Callable[[str], str | None] = _package_version,
) -> dict[str, Any]:
    """Return local capability metadata without importing or installing tools."""

    find_spec = find_spec or importlib.util.find_spec
    ffmpeg_path = which("ffmpeg")
    ffprobe_path = which("ffprobe")
    ffmpeg_available = bool(ffmpeg_path and ffprobe_path)
    whisper_spec = find_spec("whisper")
    filters = _ffmpeg_filters(ffmpeg_path) if ffmpeg_available and ffmpeg_path else frozenset()

    return {
        "local_only": True,
        "ffmpeg": {
            "available": ffmpeg_available,
            "ffmpeg": bool(ffmpeg_path),
            "ffprobe": bool(ffprobe_path),
            "version": ffmpeg_version() if ffmpeg_path else None,
        },
        "whisper": {
            "available": whisper_spec is not None,
            "version": package_version("openai-whisper") if whisper_spec else None,
            "executor": "openai-whisper",
        },
        "filters": {name: name in filters for name in ("loudnorm", "afftdn", "eq")},
    }
