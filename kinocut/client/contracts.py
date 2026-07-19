"""Public Python client method contracts for agent-safe introspection."""

from __future__ import annotations

from typing import Any

MEDIA_RETURN = "EditResult"
REPORT_RETURN = "report"

CLIENT_METHOD_CONTRACTS: dict[str, dict[str, Any]] = {
    # Core lifecycle / reports
    "info": {"category": "report", "return_type": "VideoInfo", "aliases": {}},
    "inspect": {"category": "report", "return_type": "dict", "aliases": {}},
    "pipeline": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "search_tools": {"category": "report", "return_type": "dict", "aliases": {}},
    "ingest": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    "preflight": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    "inspect_temporal": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    "verdict": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    "acceptance_eval": {
        "category": "report",
        "return_type": REPORT_RETURN,
        "aliases": {},
    },
    "body_swap": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    "salvage": {"category": "report", "return_type": REPORT_RETURN, "aliases": {}},
    # Media editing
    "trim": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"input": "input_path", "output": "output_path"},
    },
    "merge": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "add_text": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "add_audio": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "audio": "audio_path", "output": "output_path"},
    },
    "resize": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "convert": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "speed": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "thumbnail": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "extract_frame": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "preview": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "storyboard": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output_dir": "output_path"},
    },
    "subtitles": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "subtitle_file": "subtitle_path", "output": "output_path"},
    },
    "watermark": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "image": "image_path", "output": "output_path"},
    },
    "crop": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "rotate": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "fade": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "export": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "edit": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "extract_audio": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "filter": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "blur": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "reverse": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "chroma_key": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "color_grade": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "normalize_audio": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "overlay_video": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"background": "input_path", "overlay": "overlay_path", "output": "output_path"},
    },
    "split_screen": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "create_from_images": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "composite_layers": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"spec": "spec_path", "output": "output_path"},
    },
    "write_metadata": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "stabilize": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "apply_mask": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "mask": "mask_path", "output": "output_path"},
    },
    "luma_key": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "shape_mask": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "hls_segment": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path"},
    },
    # Media reports
    "detect_scenes": {"category": "report", "return_type": "SceneDetectionResult", "aliases": {"video": "input_path"}},
    "export_frames": {"category": "report", "return_type": "ImageSequenceResult", "aliases": {"video": "input_path"}},
    "generate_subtitles": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "compare_quality": {"category": "report", "return_type": "QualityMetricsResult", "aliases": {}},
    "read_metadata": {"category": "report", "return_type": "MetadataResult", "aliases": {"video": "input_path"}},
    "batch": {"category": "report", "return_type": "dict", "aliases": {}},
    # Effects/transitions/media-producing primitives
    "effect_vignette": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "effect_chromatic_aberration": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "effect_scanlines": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path", "intensity": "opacity"},
    },
    "effect_noise": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "effect_glow": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "layout_grid": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "layout_pip": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"main": "input_path", "pip": "pip_path", "output": "output_path"},
    },
    "text_animated": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "text_subtitles": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "subtitles_styled": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "mograph_count": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "mograph_progress": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "transition_glitch": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "transition_pixelate": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "transition_morph": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "video_info_detailed": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "auto_chapters": {"category": "report", "return_type": "list", "aliases": {"video": "input_path"}},
    # Audio
    "audio_waveform": {"category": "report", "return_type": "WaveformResult", "aliases": {"video": "input_path"}},
    "audio_synthesize": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "audio_preset": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "audio_sequence": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "audio_compose": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "audio_effects": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "add_generated_audio": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "audio_spatial": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "audio_bed": {
        "category": "workflow",
        "return_type": "dict",
        "aliases": {"voice": "voice_source", "music": "music_path", "output": "output_path"},
    },
    # AI
    "ai_remove_silence": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "ai_transcribe": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "analyze_video": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "ai_scene_detect": {"category": "report", "return_type": "list", "aliases": {"video": "input_path"}},
    "ai_stem_separation": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "ai_upscale": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    "ai_color_grade": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    # Hyperframes
    "hyperframes_render": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "hyperframes_still": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "hyperframes_snapshot": {"category": "report", "return_type": "HyperframesSnapshotResult", "aliases": {}},
    "hyperframes_inspect": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_info": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_catalog": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_capture": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_tts": {
        "category": "report",
        "return_type": "HyperframesJsonResult",
        "aliases": {"output": "output_path"},
    },
    "hyperframes_transcribe": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_remove_background": {
        "category": "report",
        "return_type": "HyperframesJsonResult",
        "aliases": {"output": "output_path", "background_output": "background_output_path"},
    },
    "hyperframes_doctor": {"category": "report", "return_type": "HyperframesJsonResult", "aliases": {}},
    "hyperframes_benchmark": {
        "category": "report",
        "return_type": "HyperframesJsonResult",
        "aliases": {"output": "output_path"},
    },
    "hyperframes_to_mcpvideo": {"category": "media", "return_type": MEDIA_RETURN, "aliases": {"output": "output_path"}},
    "hyperframes_compositions": {"category": "report", "return_type": "list", "aliases": {}},
    "hyperframes_preview": {"category": "report", "return_type": "dict", "aliases": {}},
    "hyperframes_init": {"category": "report", "return_type": "dict", "aliases": {"output_dir": "output_path"}},
    "hyperframes_add_block": {"category": "report", "return_type": "dict", "aliases": {}},
    "hyperframes_validate": {"category": "report", "return_type": "dict", "aliases": {}},
    "repurpose_plan": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "repurpose": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    # Image/report methods
    "extract_colors": {"category": "report", "return_type": "dict", "aliases": {}},
    "generate_palette": {"category": "report", "return_type": "dict", "aliases": {}},
    "analyze_product": {"category": "report", "return_type": "dict", "aliases": {}},
    # Quality/report methods
    "quality_check": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "assert_quality": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "release_checkpoint": {"category": "report", "return_type": "dict", "aliases": {"video": "input_path"}},
    "design_quality_check": {
        "category": "report",
        "return_type": "DesignQualityReport",
        "aliases": {"video": "input_path"},
    },
    "fix_design_issues": {
        "category": "media",
        "return_type": MEDIA_RETURN,
        "aliases": {"video": "input_path", "output": "output_path"},
    },
    # Workflow engine
    "workflow_validate": {"category": "workflow", "return_type": "dict", "aliases": {}},
    "workflow_plan": {"category": "workflow", "return_type": "dict", "aliases": {}},
    "workflow_render": {"category": "workflow", "return_type": "dict", "aliases": {}},
    "workflow_inspect": {"category": "workflow", "return_type": "dict", "aliases": {}},
    "rescue_plan": {"category": "rescue", "return_type": "dict", "aliases": {}},
    "rescue_render": {"category": "rescue", "return_type": "dict", "aliases": {}},
    "rescue_inspect": {"category": "rescue", "return_type": "dict", "aliases": {}},
    # Post-rescue planning
    "semantic_timeline": {"category": "planning", "return_type": "dict", "aliases": {}},
    "semantic_query": {"category": "planning", "return_type": "dict", "aliases": {}},
    "timeline_edit_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    "visual_transform_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    "restoration_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    "composition_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    "creative_autopilot_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    "remote_egress_plan": {"category": "planning", "return_type": "dict", "aliases": {}},
    # Release-artifact policy (public surfaces)
    "review_package": {"category": "report", "return_type": "dict", "aliases": {}},
    "publish_gate": {"category": "report", "return_type": "dict", "aliases": {}},
    "review_decision": {"category": "report", "return_type": "dict", "aliases": {}},
    "learning_report": {"category": "report", "return_type": "dict", "aliases": {}},
    "cost_ledger": {"category": "report", "return_type": "dict", "aliases": {}},
    "recipe_capture": {"category": "report", "return_type": "dict", "aliases": {}},
    "capabilities": {"category": "report", "return_type": "dict", "aliases": {}},
    "benchmark_run": {"category": "report", "return_type": "dict", "aliases": {}},
}
