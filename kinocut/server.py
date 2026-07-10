"""mcp-video MCP server — exposes video editing tools for AI agents."""

from __future__ import annotations

from .server_app import _error_result as _error_result
from .server_app import _result as _result
from .server_app import mcp as mcp
from .server_resources import (
    templates_resource as templates_resource,
    video_audio_resource as video_audio_resource,
    video_info_resource as video_info_resource,
    video_preview_resource as video_preview_resource,
)
from .server_tools_basic import (
    VALID_XFADE_TRANSITIONS as VALID_XFADE_TRANSITIONS,
    search_tools as search_tools,
    video_add_audio as video_add_audio,
    video_add_text as video_add_text,
    video_convert as video_convert,
    video_info as video_info,
    video_merge as video_merge,
    video_resize as video_resize,
    video_speed as video_speed,
    video_trim as video_trim,
)
from .server_tools_media import (
    video_crop as video_crop,
    video_edit as video_edit,
    video_export as video_export,
    video_extract_audio as video_extract_audio,
    video_fade as video_fade,
    video_preview as video_preview,
    video_rotate as video_rotate,
    video_storyboard as video_storyboard,
    video_subtitles as video_subtitles,
    video_template_preview as video_template_preview,
    video_thumbnail as video_thumbnail,
    video_watermark as video_watermark,
)
from .server_tools_advanced import (
    video_apply_mask as video_apply_mask,
    video_audio_waveform as video_audio_waveform,
    video_batch as video_batch,
    video_chroma_key as video_chroma_key,
    video_cleanup as video_cleanup,
    video_compare_quality as video_compare_quality,
    video_composite_layers as video_composite_layers,
    video_create_from_images as video_create_from_images,
    video_detect_scenes as video_detect_scenes,
    video_export_frames as video_export_frames,
    video_filter as video_filter,
    video_generate_subtitles as video_generate_subtitles,
    video_hls_segment as video_hls_segment,
    video_luma_key as video_luma_key,
    video_normalize_audio as video_normalize_audio,
    video_overlay as video_overlay,
    video_read_metadata as video_read_metadata,
    video_reverse as video_reverse,
    video_shape_mask as video_shape_mask,
    video_split_screen as video_split_screen,
    video_stabilize as video_stabilize,
    video_write_metadata as video_write_metadata,
)
from .server_tools_image import (
    image_analyze_product as image_analyze_product,
    image_extract_colors as image_extract_colors,
    image_generate_palette as image_generate_palette,
)
from .server_tools_creation import (
    shot_prompt_render as shot_prompt_render,
    storyboard_read as storyboard_read,
    style_pack_read as style_pack_read,
    video_project_create as video_project_create,
)
from .server_tools_hyperframes import (
    hyperframes_add_block as hyperframes_add_block,
    hyperframes_benchmark as hyperframes_benchmark,
    hyperframes_capture as hyperframes_capture,
    hyperframes_catalog as hyperframes_catalog,
    hyperframes_compositions as hyperframes_compositions,
    hyperframes_doctor as hyperframes_doctor,
    hyperframes_init as hyperframes_init,
    hyperframes_info as hyperframes_info,
    hyperframes_inspect as hyperframes_inspect,
    hyperframes_preview as hyperframes_preview,
    hyperframes_render as hyperframes_render,
    hyperframes_remove_background as hyperframes_remove_background,
    hyperframes_snapshot as hyperframes_snapshot,
    hyperframes_still as hyperframes_still,
    hyperframes_transcribe as hyperframes_transcribe,
    hyperframes_tts as hyperframes_tts,
    hyperframes_to_mcpvideo as hyperframes_to_mcpvideo,
    hyperframes_validate as hyperframes_validate,
)
from .server_tools_audio import (
    audio_compose as audio_compose,
    audio_effects as audio_effects,
    audio_preset as audio_preset,
    audio_sequence as audio_sequence,
    audio_synthesize as audio_synthesize,
    video_add_generated_audio as video_add_generated_audio,
    video_audio_spatial as video_audio_spatial,
)
from .server_tools_effects import (
    effect_chromatic_aberration as effect_chromatic_aberration,
    effect_glow as effect_glow,
    effect_noise as effect_noise,
    effect_scanlines as effect_scanlines,
    effect_vignette as effect_vignette,
    transition_glitch as transition_glitch,
    transition_morph as transition_morph,
    transition_pixelate as transition_pixelate,
    video_auto_chapters as video_auto_chapters,
    video_info_detailed as video_info_detailed,
    video_layout_grid as video_layout_grid,
    video_layout_pip as video_layout_pip,
    video_mograph_count as video_mograph_count,
    video_mograph_progress as video_mograph_progress,
    video_text_animated as video_text_animated,
    video_subtitles_styled as video_subtitles_styled,
)
from .server_tools_glitch import (
    glitch_cmyk_split as glitch_cmyk_split,
    glitch_datamoshing as glitch_datamoshing,
    glitch_macroblocking as glitch_macroblocking,
    glitch_rgb_shift as glitch_rgb_shift,
    glitch_scanline_jitter as glitch_scanline_jitter,
    glitch_screen_tearing as glitch_screen_tearing,
    glitch_turbulent_displacement as glitch_turbulent_displacement,
    glitch_vhs_tracking as glitch_vhs_tracking,
)
from .server_tools_glitch_shader import (
    glitch_depth_splatting as glitch_depth_splatting,
    glitch_digital_feedback as glitch_digital_feedback,
    glitch_point_cloud as glitch_point_cloud,
    glitch_slit_scan as glitch_slit_scan,
)
from .server_tools_ai import (
    video_ai_color_grade as video_ai_color_grade,
    video_ai_remove_silence as video_ai_remove_silence,
    video_ai_scene_detect as video_ai_scene_detect,
    video_ai_stem_separation as video_ai_stem_separation,
    video_ai_transcribe as video_ai_transcribe,
    video_ai_upscale as video_ai_upscale,
    video_analyze as video_analyze,
    video_design_quality_check as video_design_quality_check,
    video_fix_design_issues as video_fix_design_issues,
    video_quality_check as video_quality_check,
    video_release_checkpoint as video_release_checkpoint,
)
from .server_tools_repurpose import (
    video_repurpose as video_repurpose,
    video_repurpose_plan as video_repurpose_plan,
)
from .server_tools_guardrails import (
    video_validate_text_layout as video_validate_text_layout,
    video_extract_frame as video_extract_frame,
)
from .server_tools_workflow import (
    video_workflow_inspect as video_workflow_inspect,
    video_workflow_plan as video_workflow_plan,
    video_workflow_render as video_workflow_render,
    video_workflow_validate as video_workflow_validate,
)
from .server_tools_rescue import (
    video_rescue_inspect as video_rescue_inspect,
    video_rescue_plan as video_rescue_plan,
    video_rescue_render as video_rescue_render,
)
from .server_tools_postrescue import (
    video_composition_plan as video_composition_plan,
    video_creative_autopilot_plan as video_creative_autopilot_plan,
    video_remote_egress_plan as video_remote_egress_plan,
    video_restoration_plan as video_restoration_plan,
    video_semantic_query as video_semantic_query,
    video_semantic_timeline as video_semantic_timeline,
    video_timeline_edit_plan as video_timeline_edit_plan,
    video_visual_transform_plan as video_visual_transform_plan,
)
