"""Kinocut's public Python API."""

__version__ = "1.8.0"

from . import contracts  # stable re-export of the Wave 0 record/receipt contracts
from .client import Client
from .ai_engine import (
    ai_remove_silence,
    ai_color_grade,
    ai_transcribe,
    ai_scene_detect,
    ai_stem_separation,
    ai_upscale,
    audio_spatial,
)
from .audio_engine import (
    audio_synthesize,
    audio_preset,
    audio_sequence,
    audio_compose,
    audio_effects,
    add_generated_audio,
)
from .effects_engine import (
    effect_vignette,
    effect_chromatic_aberration,
    effect_scanlines,
    effect_noise,
    effect_glow,
    layout_grid,
    layout_pip,
    text_animated,
    text_subtitles,
    mograph_count,
    mograph_progress,
    video_info_detailed,
    auto_chapters,
)
from .transitions_engine import (
    transition_glitch,
    transition_pixelate,
    transition_morph,
)

from .quality_guardrails import assert_quality, quality_check, VisualQualityGuardrails, QualityReport
from .design_quality import (
    design_quality_check,
    fix_design_issues,
    DesignQualityGuardrails,
    DesignQualityReport,
    DesignIssue,
)

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
