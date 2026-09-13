"""Honest per-surface language coverage (P2.9 principle)."""

from __future__ import annotations

from typing import Any, Final
import shutil

# Surfaces must never conflate. Each lists languages with REAL support only.
_COVERAGE: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "transcribe": {
        "supported": ("en", "es", "multi"),  # Whisper multi; EN/ES first-class claims
        "primary": ("en", "es"),
    },
    "translate": {
        # Built-in deterministic offline path: en→es dictionary pass + identity.
        # External engines may expand; never claim without a backend.
        "supported": ("en->es", "identity"),
        "primary": ("en->es",),
    },
    "dub": {
        # Optional implemented stock caption speech; no translation or cloning.
        "supported": ("en", "es"),
        "primary": ("en", "es"),
    },
}


def language_coverage_report() -> dict[str, Any]:
    """Return honest coverage matrix for agent-facing claims."""
    surfaces: dict[str, Any] = {}
    for name, meta in _COVERAGE.items():
        supported = list(meta["supported"])
        if name == "dub" and shutil.which("espeak-ng") is None:
            supported = []
        surfaces[name] = {
            "supported_languages_or_pairs": supported,
            "primary": list(meta["primary"]),
            "available": bool(supported),
            "notes": _surface_notes(name, supported),
        }
        if name == "dub":
            surfaces[name].update(
                implemented_languages=["en", "es"],
                backend_required="espeak-ng",
                execution_surface="sound_voice_batch",
                translation_applied=False,
            )
    return {
        "artifact_kind": "language_coverage",
        "principle": "transcribe/translate/dub each state REAL coverage; never conflate",
        "brand_primary": ["en", "es"],
        "surfaces": surfaces,
    }


def _surface_notes(name: str, supported: list[str]) -> str:
    if name == "dub" and not supported:
        return "Local stock caption speech is implemented; optional espeak-ng is absent from PATH."
    if name == "dub":
        return "Stock caption speech requires a validated request and espeak-ng; PATH discovery is not render proof."
    if name == "translate":
        return "en→es offline map + identity; other pairs require an explicit backend."
    if name == "transcribe":
        return "Whisper multi-language when optional extra installed; EN/ES are brand primary."
    return ""
