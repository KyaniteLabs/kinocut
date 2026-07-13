"""Default values for Kinocut.

All default constants used across the codebase are centralized here
per AGENTS.md Rule 12.
"""

from __future__ import annotations

# Re-export encoding defaults from limits for backward compatibility
from .limits import DEFAULT_CRF, DEFAULT_FFMPEG_TIMEOUT, DEFAULT_PRESET  # noqa: F401

# Quality presets
DEFAULT_QUALITY = "high"
DEFAULT_FORMAT = "mp4"

# Legacy safe subtitle burn style. Applied as force_style to SRT/VTT when the
# caller supplies no style; authored ASS keeps its own styling and receives no
# force_style so its PlayRes/positions are preserved.
DEFAULT_SUBTITLE_STYLE = "FontSize=22,PrimaryColour=&Hffffff&,OutlineColour=&H000000&,Outline=2,Shadow=1"

# Video dimensions
DEFAULT_FPS = 30
DEFAULT_COMPOSITION_WIDTH = 1920
DEFAULT_COMPOSITION_HEIGHT = 1080
DEFAULT_COMPOSITION_FPS = DEFAULT_FPS
DEFAULT_GIF_FPS = 15
DEFAULT_THUMBNAIL_WIDTH = 320
DEFAULT_STORYBOARD_WIDTH = 480
DEFAULT_STORYBOARD_HEIGHT = 270
DEFAULT_INSPECTION_SAMPLE_PERCENTAGES = (0, 25, 50, 75, 95)
DEFAULT_MOTION_STRIP_CELL_WIDTH = 480
DEFAULT_MOTION_STRIP_CELL_HEIGHT = 270
DEFAULT_INSPECTION_IMAGE_QUALITY = 2
DEFAULT_INSPECTION_PREVIEW_MAX_SECONDS = 30.0
DEFAULT_INSPECTION_PREVIEW_WIDTH = 640
DEFAULT_INSPECTION_PREVIEW_CRF = 28
DEFAULT_INSPECTION_PREVIEW_PRESET = "veryfast"
DEFAULT_TEMPORAL_BLACK_LUMA_MAX = 8.0
DEFAULT_TEMPORAL_FROZEN_DIFFERENCE_MAX = 0.5
DEFAULT_TEMPORAL_BROKEN_LOOP_DIFFERENCE_MIN = 12.0
DEFAULT_TEMPORAL_TEXT_DRIFT_DIFFERENCE_MIN = 15.0
DEFAULT_TEMPORAL_LATE_FRAME_GAP_MULTIPLIER = 2.0
DEFAULT_TEMPORAL_ANALYSIS_WIDTH = 16
DEFAULT_TEMPORAL_ANALYSIS_HEIGHT = 16

# Audio defaults
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_AUDIO_CHANNELS = 2
DEFAULT_AUDIO_VOLUME = 0.5
DEFAULT_LUFS_TARGET = -16.0
DEFAULT_LRA_TARGET = 11.0
DEFAULT_AUDIO_BITRATE = "128k"
DEFAULT_PROCEDURAL_AUDIO_BED_WARNING_SECONDS = 10.0

# Audio-bed defaults (field-proven sidechain ducking + loudness normalization).
# The governed one-shot bed composes these with the existing duck_audio engine.
DEFAULT_AUDIO_BED_DUCK_THRESHOLD = 0.02
DEFAULT_AUDIO_BED_DUCK_RATIO = 5.0
DEFAULT_AUDIO_BED_DUCK_ATTACK_MS = 25.0
DEFAULT_AUDIO_BED_DUCK_RELEASE_MS = 450.0
DEFAULT_AUDIO_BED_LOOP_CROSSFADE = 1.5
DEFAULT_AUDIO_BED_FADE_IN = 0.0
DEFAULT_AUDIO_BED_FADE_OUT = 2.2
DEFAULT_AUDIO_BED_TARGET_LUFS = -16.0
DEFAULT_AUDIO_BED_DURATION_TOLERANCE_SECONDS = 0.35
DEFAULT_AUDIO_BED_MUSIC_VOLUME = 1.0
DEFAULT_AUDIO_BED_TRUE_PEAK_DBTP = -1.5

DEFAULT_AUDIO_BED_LOOP_MAX_PLAYS = 100

# Text overlay defaults
DEFAULT_FONT_SIZE = 48
DEFAULT_TEXT_COLOR = "white"
DEFAULT_TEXT_POSITION = "top-center"
DEFAULT_SAFE_SUBTITLE_FONT_SIZE = 24
DEFAULT_SUBTITLE_MAX_CHARS_PER_LINE = 42
DEFAULT_SUBTITLE_MAX_LINES = 3

# Agent/release guardrail defaults
MIN_FFMPEG_VERSION_HARD = 5
MIN_FFMPEG_VERSION = 6
DEFAULT_GLOW_MAX_SAFE_INTENSITY = 0.25
DEFAULT_QUALITY_GATE_SCORE = 80.0
DEFAULT_C2PA_TIMEOUT = 120

# Transition defaults
DEFAULT_TRANSITION_DURATION = 1.0

# Body-swap defaults
DEFAULT_BODY_SWAP_DURATION_TOLERANCE_SECONDS = 0.1
DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES = 1024 * 1024

# AI-video salvage verification
DEFAULT_SALVAGE_DURATION_TOLERANCE_SECONDS = 0.12
DEFAULT_SALVAGE_FREEZE_CODEC = "ffv1"
DEFAULT_SALVAGE_FREEZE_PIXEL_FORMAT = "yuv420p"

# Subtitle QA defaults — shared source of truth per AGENTS.md Rule 12.
# Tunable thresholds plus the shipped design-guardrail heuristic factors used
# to estimate subtitle bounding boxes at full display resolution.
DEFAULT_SUBTITLE_QA_READING_SPEED_CPS = 25.0
DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD = 3.0
DEFAULT_SUBTITLE_QA_CHAR_WIDTH_FACTOR = 0.6
DEFAULT_SUBTITLE_QA_LINE_HEIGHT_FACTOR = 1.2
# Deterministic detectors produce certain findings — this confidence value is
# the semantic representation of that certainty, not a tunable threshold.
DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE = 1.0

# Grid/layout defaults
DEFAULT_GRID_CELL_WIDTH = 640
DEFAULT_GRID_CELL_HEIGHT = 480

# NIMA aesthetic scoring defaults
DEFAULT_NIMA_CANDIDATES = 8
DEFAULT_NIMA_MIN_DURATION = 3.0

# Shared hashing/serialization chunk size for streaming SHA-256 over files.
# Centralized so every caller hashes at the same I/O granularity.
DEFAULT_HASH_CHUNK_BYTES = 1 << 20  # 1 MiB

# Graphics canvas defaults (applied when the caller omits the field).
DEFAULT_GRAPHICS_CANVAS_FPS = 24.0
DEFAULT_GRAPHICS_CANVAS_DURATION = 2.0
DEFAULT_GRAPHICS_CANVAS_BACKGROUND = "#000000"

# Graphics layer defaults (applied when the caller omits the field).
DEFAULT_GRAPHICS_LAYER_COLOR = "#FFFFFF"
DEFAULT_GRAPHICS_LAYER_OPACITY = 1.0
# Default graphics-layer position stored as immutable coordinate constants so
# the per-instance dict factory in GraphicsLayer cannot share mutable state
# across instances (frozen models don't deep-freeze mutable containers).
DEFAULT_GRAPHICS_LAYER_POSITION_X = 0.0
DEFAULT_GRAPHICS_LAYER_POSITION_Y = 0.0
