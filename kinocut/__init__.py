"""Kinocut's public Python API."""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.15.0"

# Heavy engines and Client stay off the import path until first attribute
# access (PEP 562). Submodule imports such as ``from kinocut import
# engine_audio_bed`` still resolve via the package fallback below.

_LAZY: dict[str, tuple[str, str | None]] = {
    "Client": (".client", "Client"),
    "DesignIssue": (".design_quality", "DesignIssue"),
    "DesignQualityGuardrails": (".design_quality", "DesignQualityGuardrails"),
    "DesignQualityReport": (".design_quality", "DesignQualityReport"),
    "QualityReport": (".quality_guardrails", "QualityReport"),
    "VisualQualityGuardrails": (".quality_guardrails", "VisualQualityGuardrails"),
    "add_generated_audio": (".audio_engine", "add_generated_audio"),
    "ai_color_grade": (".ai_engine", "ai_color_grade"),
    "ai_remove_silence": (".ai_engine", "ai_remove_silence"),
    "ai_scene_detect": (".ai_engine", "ai_scene_detect"),
    "ai_stem_separation": (".ai_engine", "ai_stem_separation"),
    "ai_transcribe": (".ai_engine", "ai_transcribe"),
    "ai_upscale": (".ai_engine", "ai_upscale"),
    "assert_quality": (".quality_guardrails", "assert_quality"),
    "audio_compose": (".audio_engine", "audio_compose"),
    "audio_effects": (".audio_engine", "audio_effects"),
    "audio_preset": (".audio_engine", "audio_preset"),
    "audio_sequence": (".audio_engine", "audio_sequence"),
    "audio_spatial": (".ai_engine", "audio_spatial"),
    "audio_synthesize": (".audio_engine", "audio_synthesize"),
    "auto_chapters": (".effects_engine", "auto_chapters"),
    "contracts": (".contracts", None),
    "design_quality_check": (".design_quality", "design_quality_check"),
    "effect_chromatic_aberration": (".effects_engine", "effect_chromatic_aberration"),
    "effect_glow": (".effects_engine", "effect_glow"),
    "effect_noise": (".effects_engine", "effect_noise"),
    "effect_scanlines": (".effects_engine", "effect_scanlines"),
    "effect_vignette": (".effects_engine", "effect_vignette"),
    "fix_design_issues": (".design_quality", "fix_design_issues"),
    "layout_grid": (".effects_engine", "layout_grid"),
    "layout_pip": (".effects_engine", "layout_pip"),
    "mograph_count": (".effects_engine", "mograph_count"),
    "mograph_progress": (".effects_engine", "mograph_progress"),
    "quality_check": (".quality_guardrails", "quality_check"),
    "text_animated": (".effects_engine", "text_animated"),
    "text_subtitles": (".effects_engine", "text_subtitles"),
    "transition_glitch": (".transitions_engine", "transition_glitch"),
    "transition_morph": (".transitions_engine", "transition_morph"),
    "transition_pixelate": (".transitions_engine", "transition_pixelate"),
    "video_info_detailed": (".effects_engine", "video_info_detailed"),
}

__all__ = [
    "Client",
    "DesignIssue",
    "DesignQualityGuardrails",
    "DesignQualityReport",
    "QualityReport",
    "VisualQualityGuardrails",
    "add_generated_audio",
    "ai_color_grade",
    "ai_remove_silence",
    "ai_scene_detect",
    "ai_stem_separation",
    "ai_transcribe",
    "ai_upscale",
    "assert_quality",
    "audio_compose",
    "audio_effects",
    "audio_preset",
    "audio_sequence",
    "audio_spatial",
    "audio_synthesize",
    "auto_chapters",
    "contracts",
    "design_quality_check",
    "effect_chromatic_aberration",
    "effect_glow",
    "effect_noise",
    "effect_scanlines",
    "effect_vignette",
    "fix_design_issues",
    "layout_grid",
    "layout_pip",
    "mograph_count",
    "mograph_progress",
    "quality_check",
    "text_animated",
    "text_subtitles",
    "transition_glitch",
    "transition_morph",
    "transition_pixelate",
    "video_info_detailed",
]


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is not None:
        module_name, attr = spec
        module = importlib.import_module(module_name, __name__)
        value = module if attr is None else getattr(module, attr)
        globals()[name] = value
        return value
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
