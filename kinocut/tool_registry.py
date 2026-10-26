"""Declarative MCP tool profiles and lazy registration.

The server owns one complete tool catalog, but only the selected profile is
registered with MCP.  Hidden tools remain searchable: discovery loads the
catalog on demand and restores the selected registration surface afterwards.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable, Mapping
from typing import Any


# Keep this table boring and reviewable.  The registration module is a
# deliberate boundary: adding a tool requires assigning it to a profile here,
# rather than editing a second set of conditional registration branches.
TOOL_NAMES_BY_MODULE: Mapping[str, tuple[str, ...]] = {
    "server_tools_advanced": (
        "video_filter",
        "video_luma_key",
        "video_shape_mask",
        "video_hls_segment",
        "video_reverse",
        "video_chroma_key",
        "video_normalize_audio",
        "video_overlay",
        "video_split_screen",
        "video_detect_scenes",
        "video_create_from_images",
        "video_export_frames",
        "video_generate_subtitles",
        "video_compare_quality",
        "video_read_metadata",
        "video_write_metadata",
        "video_stabilize",
        "video_apply_mask",
        "video_audio_waveform",
        "video_batch",
        "video_cleanup",
        "video_composite_layers",
    ),
    "server_tools_ai": (
        "video_ai_remove_silence",
        "video_ai_transcribe",
        "video_analyze",
        "video_ai_scene_detect",
        "video_ai_stem_separation",
        "video_ai_upscale",
        "video_ai_color_grade",
        "video_quality_check",
        "video_release_checkpoint",
        "video_design_quality_check",
        "video_fix_design_issues",
    ),
    "server_tools_aivideo": (
        "video_verdict",
        "video_acceptance_eval",
        "video_body_swap",
        "video_salvage",
    ),
    "server_tools_audio": (
        "video_mix_audio",
        "audio_synthesize",
        "audio_preset",
        "audio_sequence",
        "audio_compose",
        "audio_effects",
        "video_add_generated_audio",
        "video_audio_spatial",
        "video_duck_audio",
        "video_audio_bed",
    ),
    "server_tools_basic": (
        "video_info",
        "video_trim",
        "video_merge",
        "video_add_text",
        "video_add_texts",
        "video_add_audio",
        "video_resize",
        "video_convert",
        "video_speed",
        "search_tools",
    ),
    "server_tools_creation": (
        "video_project_create",
        "style_pack_read",
        "storyboard_read",
        "shot_prompt_render",
    ),
    "server_tools_doctor": ("video_doctor",),
    "server_tools_effects": (
        "effect_vignette",
        "effect_chromatic_aberration",
        "effect_scanlines",
        "effect_noise",
        "effect_glow",
        "video_layout_grid",
        "video_layout_pip",
        "video_text_animated",
        "video_subtitles_styled",
        "video_mograph_count",
        "video_mograph_progress",
        "video_info_detailed",
        "video_auto_chapters",
        "transition_glitch",
        "transition_pixelate",
        "transition_morph",
    ),
    "server_tools_glitch": (
        "glitch_rgb_shift",
        "glitch_scanline_jitter",
        "glitch_screen_tearing",
        "glitch_vhs_tracking",
        "glitch_macroblocking",
        "glitch_datamoshing",
        "glitch_cmyk_split",
        "glitch_turbulent_displacement",
    ),
    "server_tools_glitch_shader": (
        "glitch_digital_feedback",
        "glitch_slit_scan",
        "glitch_depth_splatting",
        "glitch_point_cloud",
    ),
    "server_tools_guardrails": (
        "video_validate_text_layout",
        "video_extract_frame",
    ),
    "server_tools_hyperframes": (
        "hyperframes_render",
        "hyperframes_compositions",
        "hyperframes_preview",
        "hyperframes_still",
        "hyperframes_snapshot",
        "hyperframes_inspect",
        "hyperframes_info",
        "hyperframes_catalog",
        "hyperframes_capture",
        "hyperframes_tts",
        "hyperframes_transcribe",
        "hyperframes_remove_background",
        "hyperframes_doctor",
        "hyperframes_benchmark",
        "hyperframes_init",
        "hyperframes_add_block",
        "hyperframes_validate",
        "hyperframes_to_mcpvideo",
    ),
    "server_tools_image": (
        "image_extract_colors",
        "image_generate_palette",
        "image_analyze_product",
        "still_match",
        "still_grade",
        "still_gate",
        "image_edit",
        "still_package",
    ),
    "server_tools_inspection": (
        "video_ingest",
        "video_preflight",
        "video_inspect_temporal",
    ),
    "server_tools_intent": (
        "video_find_moments",
        "video_project_recipe_export",
        "video_project_recipe_replay",
        "video_intent",
        "video_propose_broll",
        "video_translate_captions",
        "video_language_coverage",
        "video_review_run",
        "video_review_decide",
        "video_propose_mutations",
        "video_init_project",
        "video_brand_kit",
        "video_estimate_operation",
        "video_cutfile_validate",
        "video_cutfile_render",
        "video_metric_qc",
        "video_timeline_ir_validate",
        "video_qc_vision",
        "video_qc_narrative",
        "video_generative_plan",
        "video_otio_export",
        "video_otio_import",
        "video_review_ui",
        "video_dub_plan",
        "video_publish_validate",
        "video_hook_candidates",
        "video_audiogram_plan",
        "video_punch_zoom_plan",
        "video_seek_frame",
        "video_edit_session",
    ),
    "server_tools_media": (
        "video_thumbnail",
        "video_preview",
        "video_storyboard",
        "video_subtitles",
        "video_watermark",
        "video_export",
        "video_crop",
        "video_rotate",
        "video_fade",
        "video_edit",
        "video_template_preview",
        "video_extract_audio",
    ),
    "server_tools_motion_acceptance": ("video_record_motion_acceptance",),
    "server_tools_postrescue": (
        "video_semantic_timeline",
        "video_semantic_query",
        "video_timeline_edit_plan",
        "video_visual_transform_plan",
        "video_restoration_plan",
        "video_composition_plan",
        "video_creative_autopilot_plan",
        "video_remote_egress_plan",
    ),
    "server_tools_release": (
        "video_review_package",
        "video_publish_gate",
        "video_review_decision",
        "video_learning_report",
        "video_cost_ledger",
        "video_recipe_capture",
        "video_capabilities",
        "video_benchmark_run",
    ),
    "server_tools_repurpose": ("video_repurpose_plan", "video_repurpose"),
    "server_tools_rescue": ("video_rescue_plan", "video_rescue_render", "video_rescue_inspect"),
    "server_tools_revideo": ("revideo_materialize", "revideo_install", "revideo_render", "revideo_render_job"),
    "server_tools_shorts": ("video_shorts", "shorts_plan_show", "shorts_review", "shorts_render", "shorts_package"),
    "server_tools_sound": (
        "sound_capabilities",
        "sound_plan_validate",
        "sound_voice_batch",
        "sound_mix_render",
        "sound_master_render",
        "sound_qa_loudness",
        "sound_qa_asr",
    ),
    "server_tools_workflow": (
        "video_workflow_validate",
        "video_workflow_plan",
        "video_workflow_render",
        "video_workflow_inspect",
    ),
}

MODULE_PROFILE_TAGS: Mapping[str, tuple[str, ...]] = {
    "server_tools_advanced": ("editor", "advanced"),
    "server_tools_ai": ("ai",),
    "server_tools_aivideo": ("ai",),
    "server_tools_audio": ("editor", "audio"),
    "server_tools_basic": ("editor",),
    "server_tools_creation": ("editor", "creation"),
    "server_tools_doctor": ("inspection",),
    "server_tools_effects": ("editor", "effects"),
    "server_tools_glitch": ("hidden",),
    "server_tools_glitch_shader": ("hidden",),
    "server_tools_guardrails": ("editor", "guardrails"),
    "server_tools_hyperframes": ("hyperframes",),
    "server_tools_image": ("image",),
    "server_tools_inspection": ("editor", "inspection"),
    "server_tools_intent": ("intent",),
    "server_tools_media": ("editor", "media"),
    "server_tools_motion_acceptance": ("editor", "inspection"),
    "server_tools_postrescue": ("postrescue",),
    "server_tools_release": ("release",),
    "server_tools_repurpose": ("editor", "repurpose"),
    "server_tools_rescue": ("rescue",),
    "server_tools_revideo": ("revideo",),
    "server_tools_shorts": ("editor", "shorts"),
    "server_tools_sound": ("audio",),
    "server_tools_workflow": ("editor", "workflow"),
}

# The default is intentionally small enough to fit a one-screen tool list,
# while retaining the common edit path, inspection, receipts, and diagnostics.
CORE_TOOLS = frozenset(
    {
        "video_info",
        "video_trim",
        "video_merge",
        "video_add_text",
        "video_add_texts",
        "video_add_audio",
        "video_resize",
        "video_convert",
        "video_speed",
        "search_tools",
        "video_extract_frame",
        "video_validate_text_layout",
        "video_quality_check",
        "video_review_package",
        "video_workflow_inspect",
        "video_rescue_inspect",
        "hyperframes_doctor",
        "video_doctor",
        "video_shorts",
        "video_project_create",
    }
)

TOOL_MODULE_BY_NAME = {name: module for module, names in TOOL_NAMES_BY_MODULE.items() for name in names}

# Public, inspectable table: tool name -> profile tags.  ``core`` is additive;
# ``all`` is an explicit mode and therefore does not need to be repeated on
# every row.
TOOL_REGISTRY: dict[str, tuple[str, ...]] = {
    name: tuple(sorted({*MODULE_PROFILE_TAGS[module], *(("core",) if name in CORE_TOOLS else ())}))
    for module, names in TOOL_NAMES_BY_MODULE.items()
    for name in names
}

if CORE_TOOLS - TOOL_MODULE_BY_NAME.keys():
    raise RuntimeError("MCP core tool table names an unregistered tool")

_TOOL_CATALOG: dict[str, dict[str, Any]] = {}
_ACTIVE_MODE = "default"
_ACTIVE_PROFILES = frozenset({"core"})


def parse_tool_mode(raw: str | None = None) -> tuple[str, frozenset[str]]:
    """Resolve ``KINOCUT_TOOLS`` into a stable mode and profile set."""

    value = (raw if raw is not None else os.environ.get("KINOCUT_TOOLS", "")).strip().lower()
    if not value or value == "core":
        return "default", frozenset({"core"})
    if value == "all":
        return "all", frozenset()
    profiles = frozenset(part.removeprefix("profile:").strip() for part in value.split(",") if part.strip())
    known = {tag for tags in TOOL_REGISTRY.values() for tag in tags} - {"core"}
    unknown = profiles - known
    if (
        unknown
        or not profiles
        or any("profile:" not in part and part.strip() not in known for part in value.split(","))
    ):
        allowed = ", ".join(sorted(known))
        raise ValueError(f"KINOCUT_TOOLS must be all, core, or profile:<name> (available: {allowed})")
    return f"profile:{','.join(sorted(profiles))}", profiles | {"core"}


def _tool_manager() -> Any:
    from .server_app import mcp

    return mcp._tool_manager


def _capture_catalog(tool_manager: Any | None = None) -> None:
    tools = (tool_manager or _tool_manager())._tools
    for name, tool in tools.items():
        _TOOL_CATALOG[name] = {
            "name": name,
            "description": tool.description or "",
            "required_params": list((tool.parameters or {}).get("required", [])),
        }


def _allowed_names(mode: str, profiles: Iterable[str]) -> frozenset[str]:
    if mode == "all":
        return frozenset(TOOL_REGISTRY)
    selected = set(profiles)
    return frozenset(name for name, tags in TOOL_REGISTRY.items() if selected.intersection(tags))


def apply_tool_surface(tool_manager: Any | None = None) -> None:
    """Remove non-selected registrations without changing any tool behavior."""

    allowed = _allowed_names(_ACTIVE_MODE, _ACTIVE_PROFILES)
    manager = tool_manager or _tool_manager()
    _capture_catalog(manager)
    tools = manager._tools
    for name in tuple(tools):
        if name not in allowed:
            del tools[name]


def configure_tool_surface(raw: str | None = None) -> None:
    """Load and register the requested MCP surface."""

    global _ACTIVE_MODE, _ACTIVE_PROFILES
    mode, profiles = parse_tool_mode(raw)
    _ACTIVE_MODE = mode
    _ACTIVE_PROFILES = profiles
    modules = (
        TOOL_NAMES_BY_MODULE
        if mode == "all" or mode.startswith("profile:")
        else {
            module: names for module, names in TOOL_NAMES_BY_MODULE.items() if any(name in CORE_TOOLS for name in names)
        }
    )
    for module, names in modules.items():
        imported = importlib.import_module(f".{module}", __package__)
        if mode == "all" or mode.startswith("profile:"):
            tools = _tool_manager()._tools
            if any(name not in tools for name in names):
                for name in names:
                    tools.pop(name, None)
                importlib.reload(imported)
    _capture_catalog()
    apply_tool_surface()


def ensure_tool_loaded(name: str) -> Any:
    """Import one tool's module for compatibility imports and return it."""

    module = TOOL_MODULE_BY_NAME.get(name)
    if module is None:
        raise AttributeError(name)
    imported = importlib.import_module(f".{module}", __package__)
    _capture_catalog()
    apply_tool_surface()
    return getattr(imported, name)


def discovery_catalog() -> list[dict[str, Any]]:
    """Load the complete registry only when an agent asks for discovery."""

    global _ACTIVE_MODE
    active_mode = _ACTIVE_MODE
    for module, names in TOOL_NAMES_BY_MODULE.items():
        imported = importlib.import_module(f".{module}", __package__)
        tools = _tool_manager()._tools
        if any(name not in tools for name in names):
            for name in names:
                tools.pop(name, None)
            importlib.reload(imported)
    _capture_catalog()
    _ACTIVE_MODE = active_mode
    apply_tool_surface()
    return [_TOOL_CATALOG[name] for name in TOOL_REGISTRY if name in _TOOL_CATALOG]


def active_mode() -> str:
    return _ACTIVE_MODE
