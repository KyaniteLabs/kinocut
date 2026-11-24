"""Side-effect-free discovery of local rescue executors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import re
from typing import Any

from ..host_probes import HostProbes, local_digest, whisper_model_path as whisper_model_path


def captions_available(capabilities: Mapping[str, Any]) -> bool:
    """Whisper needs local base weights and FFmpeg audio resampling to 16 kHz."""
    models = capabilities.get("whisper_models")
    base = models.get("base") if isinstance(models, Mapping) else None
    filters = capabilities.get("filters")
    engines = (capabilities.get("ffmpeg"), capabilities.get("whisper"), base)
    return all(isinstance(item, Mapping) and item.get("available") is True for item in engines) and (
        isinstance(filters, Mapping) and filters.get("aresample") is True
    )


def snapshot_capabilities(
    *,
    which: Callable[[str], str | None] | None = None,
    find_spec: Callable[[str], Any] | None = None,
    package_version: Callable[[str], str | None] | None = None,
    probes: HostProbes | None = None,
) -> dict[str, Any]:
    """Return local capability metadata without importing or installing tools."""

    probes = probes or HostProbes()
    probes = replace(
        probes,
        which=which or probes.which,
        find_spec=find_spec or probes.find_spec,
        package_version=package_version or probes.package_version,
    )
    ffmpeg_path = probes.which("ffmpeg")
    ffprobe_path = probes.which("ffprobe")
    ffmpeg_available = bool(ffmpeg_path and ffprobe_path)
    whisper_spec = probes.find_spec("whisper")
    base_model_sha256 = local_digest(probes.model_path("base")) if whisper_spec is not None else None
    filters = probes.filters(ffmpeg_path) if ffmpeg_available else frozenset()
    version_line = probes.command_version(["ffmpeg", "-version"], ffmpeg_path) if ffmpeg_path else None
    version = re.search(r"ffmpeg version (\S+)", version_line or "", re.IGNORECASE)

    return {
        "local_only": True,
        "ffmpeg": {
            "available": ffmpeg_available,
            "ffmpeg": bool(ffmpeg_path),
            "ffprobe": bool(ffprobe_path),
            "version": version.group(1) if version else None,
        },
        "whisper": {
            "available": whisper_spec is not None,
            "version": probes.package_version("openai-whisper") if whisper_spec is not None else None,
            "executor": "openai-whisper",
        },
        "whisper_models": {
            "base": {"available": base_model_sha256 is not None, "sha256": base_model_sha256},
        },
        "filters": {name: name in filters for name in ("loudnorm", "afftdn", "eq", "aresample", "transpose")},
    }
