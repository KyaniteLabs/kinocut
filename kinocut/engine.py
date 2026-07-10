"""FFmpeg engine — all video processing operations."""

from __future__ import annotations


from .ffmpeg_helpers import _escape_ffmpeg_filter_value as _escape_ffmpeg_filter_value
from .engine_audio_waveform import audio_waveform as audio_waveform
from .engine_audio_ops import add_audio as add_audio
from .engine_audio_normalize import normalize_audio as normalize_audio
from .engine_batch import video_batch as _video_batch
from .engine_chroma_key import chroma_key as chroma_key
from .engine_compare_quality import compare_quality as compare_quality
from .engine_composite_layers import composite_layers as composite_layers
from .engine_convert import convert as convert
from .engine_crop import crop as crop
from .engine_detect_scenes import detect_scenes as detect_scenes
from .engine_edit import trim as trim
from .engine_export import export_video as export_video
from .engine_extract_audio import extract_audio as extract_audio
from .engine_frames import export_frames as export_frames
from .engine_hls import hls_segment as hls_segment
from .engine_advanced_mask import luma_key as luma_key
from .engine_advanced_mask import shape_mask as shape_mask
from .engine_filters import _build_pitch_shift_filter as _build_pitch_shift_filter
from .engine_filters import _get_color_preset_filter as _get_color_preset_filter
from .engine_filters import apply_filter as _apply_filter
from .engine_images import create_from_images as create_from_images
from .engine_mask import apply_mask as _apply_mask
from .engine_merge import merge as merge
from .engine_metadata import read_metadata as read_metadata
from .engine_metadata import write_metadata as write_metadata
from .engine_overlay import overlay_video as _overlay_video
from .engine_preview import preview as preview
from .engine_repurpose import repurpose as repurpose
from .engine_repurpose import repurpose_plan as repurpose_plan

# Compatibility re-export: callers still import get_duration from mcp_video.engine.
from .engine_probe import get_duration as get_duration
from .engine_probe import probe as probe
from .engine_probe import probe_audio_input as probe_audio_input
from .engine_resize import resize as resize
from .engine_rotate import rotate as rotate
from .engine_reverse import reverse as reverse
from .engine_fade import fade as fade
from .engine_runtime_utils import (
    _check_filter_available as _check_filter_available,
    _default_font as _default_font,
    _ffmpeg as _ffmpeg,
    _ffprobe as _ffprobe,
    _generate_thumbnail_base64 as _generate_thumbnail_base64,
    _get_audio_stream as _get_audio_stream,
    _get_video_stream as _get_video_stream,
    _has_audio as _has_audio,
    _movflags_args as _movflags_args,
    _quality_args as _quality_args,
    _require_filter as _require_filter,
)
from .ffmpeg_helpers import (
    _parse_ffmpeg_time as _parse_ffmpeg_time,
    _run_ffmpeg as _run_ffmpeg,
    _run_ffmpeg_with_progress as _run_ffmpeg_with_progress,
    _sanitize_ffmpeg_number as _sanitize_ffmpeg_number,
)
from .models import (
    _position_coords as _position_coords,
    _resolve_position as _resolve_position,
    _validate_position as _validate_position,
)
from .paths import (
    _auto_output as _auto_output,
    _auto_output_dir as _auto_output_dir,
)
from .validation import (
    _validate_chroma_color as _validate_chroma_color,
    _validate_color as _validate_color,
)
from .engine_speed import speed as speed
from .engine_stabilize import stabilize as stabilize
from .engine_storyboard import storyboard as storyboard
from .engine_split_screen import split_screen as _split_screen
from .engine_subtitle_generate import generate_subtitles as generate_subtitles
from .engine_subtitles import subtitles as subtitles
from .engine_text import add_text as add_text
from .engine_text import add_texts as add_texts
from .engine_thumbnail import thumbnail as thumbnail
from .engine_timeline import _apply_composite_overlays as _apply_composite_overlays
from .engine_timeline import edit_timeline as edit_timeline
from .engine_transcode import normalize as normalize
from .engine_watermark import watermark as watermark
from .engine_glitch import glitch_rgb_shift as glitch_rgb_shift
from .engine_glitch import glitch_scanline_jitter as glitch_scanline_jitter
from .engine_glitch import glitch_screen_tearing as glitch_screen_tearing
from .engine_glitch import glitch_vhs_tracking as glitch_vhs_tracking
from .engine_glitch import glitch_macroblocking as glitch_macroblocking
from .engine_glitch import glitch_datamoshing as glitch_datamoshing
from .engine_glitch import glitch_cmyk_split as glitch_cmyk_split
from .engine_glitch import glitch_turbulent_displacement as glitch_turbulent_displacement
from .engine_glitch_shader import glitch_digital_feedback as glitch_digital_feedback
from .engine_glitch_shader import glitch_slit_scan as glitch_slit_scan
from .engine_glitch_shader import glitch_depth_splatting as glitch_depth_splatting
from .engine_glitch_shader import glitch_point_cloud as glitch_point_cloud

apply_mask = _apply_mask
apply_filter = _apply_filter
overlay_video = _overlay_video
split_screen = _split_screen
video_batch = _video_batch


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
