"""Local TTS dubbing plan — ES-first (P4.4). Does not invent voices."""

from __future__ import annotations

import importlib.util
import logging
import shutil
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.intent.language_coverage import language_coverage_report

logger = logging.getLogger(__name__)


def detect_tts_backend() -> dict[str, Any]:
    """Detect local TTS candidates without claiming an execution adapter."""
    backends: list[dict[str, Any]] = []
    # Hyperframes local TTS CLI (optional integration).
    if shutil.which("hyperframes"):
        backends.append({"id": "hyperframes", "kind": "cli"})
    # Optional Python packages commonly used for local TTS.
    for mod_name, kind in (("edge_tts", "python"), ("piper", "python"), ("TTS", "python")):
        try:
            if importlib.util.find_spec(mod_name) is not None:
                backends.append({"id": mod_name, "kind": kind})
        except Exception as exc:
            logger.debug("TTS backend probe skipped for %s: %s", mod_name, exc)
            continue
    primary = backends[0]["id"] if backends else None
    return {
        "available": bool(backends),
        "primary": primary,
        "backends": backends,
    }


def _candidate_metadata(report: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        {"id": str(candidate.get("id", "")), "kind": str(candidate.get("kind", ""))}
        for candidate in report.get("backends", [])
        if isinstance(candidate, dict)
    ]
    return {
        "available": bool(candidates),
        "primary": report.get("primary") if candidates else None,
        "backends": candidates,
    }


def plan_tts_dub(
    caption_path: str,
    *,
    target_lang: str = "es",
    voice: str | None = None,
) -> dict[str, Any]:
    """Return candidate metadata; no synthesis adapter exists in this tree."""
    if not isinstance(caption_path, str) or not caption_path.strip():
        raise MCPVideoError("caption_path required", error_type="validation_error", code="caption_required")
    if not isinstance(target_lang, str):
        raise MCPVideoError(
            "target_lang must be a string",
            error_type="validation_error",
            code="invalid_target_lang",
        )
    lang = (target_lang or "es").lower()
    coverage = language_coverage_report()
    dub_supported = list(coverage["surfaces"]["dub"]["supported_languages_or_pairs"])
    backend = _candidate_metadata(detect_tts_backend())
    reason = "Local candidates may be detected, but discovery is not execution; no synthesis adapter exists"
    next_action = "implement_and_verify_tts_synthesis_adapter"
    return {
        "artifact_kind": "tts_dub_plan",
        "caption_path": caption_path,
        "target_lang": lang,
        "voice": voice or ("es_default" if lang == "es" else "default"),
        "brand_primary": lang == "es",
        "executable": False,
        "reason": reason,
        "coverage": coverage,
        "supported_now": dub_supported,
        "backend": backend,
        "next_action": next_action,
    }
