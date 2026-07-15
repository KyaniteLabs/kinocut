"""Capability discovery: a structured capability report (#54, design §4.10).

A deterministic, read-only projection over :func:`run_diagnostics` that emits one
:class:`~kinocut.contracts.capability.CapabilityReport` per cataloged capability.
A capability is ``available`` (on all of MCP/Python/CLI) when every required
runtime dependency is present, or ``unavailable`` (on no surface) with a bounded
reason code and short advisory remediation when a required dependency is missing.
This is structured data an agent can read without parsing CLI help.
"""

from __future__ import annotations

from typing import Any

from kinocut.contracts.capability import (
    AvailabilityState,
    CapabilityReport,
    SurfaceAvailability,
)
from kinocut.doctor import run_diagnostics

# Catalog of public capabilities and the runtime dependencies they require.
# Required deps gate availability; optional deps enrich but never gate it.
# Dep *codes* are code-friendly (underscores); _DEP_CHECK maps them to the
# diagnostics check name (which may use hyphens, e.g. openai-whisper).
_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "video_edit", "required": ("ffmpeg",),
     "formats": ("mp4", "mov", "webm", "mkv", "avi")},
    {"id": "subtitles", "required": ("ffmpeg",), "formats": ("srt", "vtt", "ass")},
    {"id": "audio", "required": ("ffmpeg",),
     "formats": ("wav", "mp3", "aac", "flac", "ogg")},
    {"id": "ai_transcribe", "required": ("openai_whisper",), "formats": ("srt", "vtt")},
    {"id": "c2pa_signing", "required": (), "optional": ("c2patool",), "formats": ()},
)

_DEP_CHECK = {
    "ffmpeg": "ffmpeg",
    "openai_whisper": "openai-whisper",
    "c2patool": "c2patool",
}

_ALL = SurfaceAvailability(mcp=True, python=True, cli=True)
_NONE = SurfaceAvailability(mcp=False, python=False, cli=False)


def capability_report(diagnostics: dict[str, Any] | None = None) -> list[CapabilityReport]:
    """Return one capability report per cataloged capability.

    Pass ``diagnostics`` (a :func:`run_diagnostics` payload) to avoid a live
    probe; omit it to run diagnostics against the current host.
    """

    diag = diagnostics if diagnostics is not None else run_diagnostics()
    checks = {check["name"]: check for check in diag.get("checks", []) if "name" in check}
    reports: list[CapabilityReport] = []
    for capability in _CATALOG:
        required = tuple(capability["required"])
        optional = tuple(capability.get("optional", ()))
        formats = tuple(capability.get("formats", ()))
        missing = [
            dep for dep in required
            if not checks.get(_DEP_CHECK.get(dep, dep), {}).get("ok", False)
        ]
        if not missing:
            reports.append(
                CapabilityReport(
                    capability_id=capability["id"],
                    surfaces=_ALL,
                    supported_formats=formats,
                    required_deps=required,
                    optional_deps=optional,
                    availability=AvailabilityState.AVAILABLE,
                )
            )
        else:
            reports.append(
                CapabilityReport(
                    capability_id=capability["id"],
                    surfaces=_NONE,
                    supported_formats=formats,
                    required_deps=required,
                    optional_deps=optional,
                    availability=AvailabilityState.UNAVAILABLE,
                    reason_code="required_dep_missing",
                    remediation=(
                        "required dependency " + " and ".join(missing)
                        + " is missing, install it to enable this capability"
                    ),
                )
            )
    return reports


__all__ = ["capability_report"]
