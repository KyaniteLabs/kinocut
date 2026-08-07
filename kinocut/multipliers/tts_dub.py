"""Local TTS dubbing plan — ES-first (P4.4). Does not invent voices."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.intent.language_coverage import language_coverage_report


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
    # Plan surface exists; actual synth is still capability-gated.
    return {
        "artifact_kind": "tts_dub_plan",
        "caption_path": caption_path,
        "target_lang": lang,
        "voice": voice or ("es_default" if lang == "es" else "default"),
        "brand_primary": lang == "es",
        "executable": False,
        "reason": "Local TTS backend not bundled; plan only until a doctor-visible engine is configured",
        "coverage": coverage,
        "supported_now": dub_supported,
        "next_action": "install_local_tts_backend",
    }
