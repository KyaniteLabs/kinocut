"""Local TTS dubbing plan — ES-first (P4.4). Does not invent voices."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.intent.language_coverage import language_coverage_report


def detect_tts_backend() -> dict[str, Any]:
    """Doctor-visible TTS backend probe (no network, no synthesis)."""
    backends: list[dict[str, Any]] = []
    # Hyperframes local TTS CLI (optional integration).
    hf = shutil.which("hyperframes") or shutil.which("hf")
    if hf:
        backends.append({"id": "hyperframes", "path": hf, "kind": "cli"})
    # Optional Python packages commonly used for local TTS.
    for mod_name, kind in (("edge_tts", "python"), ("piper", "python"), ("TTS", "python")):
        try:
            if importlib.util.find_spec(mod_name) is not None:
                backends.append({"id": mod_name, "path": None, "kind": kind})
        except Exception:
            continue
    primary = backends[0]["id"] if backends else None
    return {
        "available": bool(backends),
        "primary": primary,
        "backends": backends,
    }


def plan_tts_dub(
    caption_path: str,
    *,
    target_lang: str = "es",
    voice: str | None = None,
) -> dict[str, Any]:
    """Return a dub plan with honest coverage. Execution requires optional TTS backend."""
    if not caption_path:
        raise MCPVideoError("caption_path required", error_type="validation_error", code="caption_required")
    lang = (target_lang or "es").lower()
    coverage = language_coverage_report()
    dub_supported = list(coverage["surfaces"]["dub"]["supported_languages_or_pairs"])
    backend = detect_tts_backend()
    executable = bool(backend.get("available"))
    if executable:
        reason = f"TTS backend detected ({backend.get('primary')}); plan ready for explicit synth call"
        next_action = "run_hyperframes_tts_or_configured_backend"
    else:
        reason = "Local TTS backend not bundled; plan only until a doctor-visible engine is configured"
        next_action = "install_local_tts_backend"
    return {
        "artifact_kind": "tts_dub_plan",
        "caption_path": caption_path,
        "target_lang": lang,
        "voice": voice or ("es_default" if lang == "es" else "default"),
        "brand_primary": lang == "es",
        "executable": executable,
        "reason": reason,
        "coverage": coverage,
        "supported_now": dub_supported,
        "backend": backend,
        "next_action": next_action,
    }
