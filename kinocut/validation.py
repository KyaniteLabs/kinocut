"""Shared validation constants and functions for Kinocut."""

from __future__ import annotations

import re
from typing import NamedTuple

from .errors import MCPVideoError
from .limits import *  # noqa: F403 — re-export all limit constants

# Closed severity ordering used by governed acceptance evaluation. Keeping the
# policy here avoids each workflow inventing a subtly different comparison.
DEFECT_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

VALID_FORMATS = {"mp4", "webm", "gif", "mov", "hevc", "av1", "prores"}
VALID_AUDIO_FORMATS = {"mp3", "aac", "wav", "ogg", "flac"}
VALID_PRESETS = {"ultrafast", "fast", "medium", "slow", "veryslow"}
VALID_CODECS = {"h264", "h265", "vp8", "vp9", "prores", "gif"}
AUDIO_BED_SAFE_DISPLAY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
AUDIO_BED_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
AUDIO_BED_SAFE_TOOLCHAIN_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

VALID_XFADE_TRANSITIONS = {
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "circlecrop",
    "radial",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
}
VALID_WAVEFORMS = {"sine", "square", "sawtooth", "triangle", "noise", "pulse", "supersaw", "pluck", "fm"}

# Subtitle ``force_style``: the closed set of accepted ASS style keys (compared
# case-insensitively) plus the safe value character class. Values are validated
# against this class and then FFmpeg-escaped as defense in depth before being
# embedded in the subtitles filter.
SUBTITLE_STYLE_KEYS = frozenset(
    {
        "fontname",
        "fontsize",
        "primarycolour",
        "secondarycolour",
        "outlinecolour",
        "backcolour",
        "bold",
        "italic",
        "underline",
        "strikeout",
        "scalex",
        "scaley",
        "spacing",
        "angle",
        "borderstyle",
        "outline",
        "shadow",
        "alignment",
        "marginl",
        "marginr",
        "marginv",
        "encoding",
    }
)
SUBTITLE_STYLE_VALUE_RE = re.compile(r"^[A-Za-z0-9&#.+\- ]+$")
VALID_AUDIO_EFFECT_TYPES = {
    "lowpass",
    "highpass",
    "reverb",
    "normalize",
    "fade",
    "delay",
    "chorus",
    "flanger",
    "distortion",
    "compressor",
    "eq",
    "tremolo",
    "vibrato",
}
VALID_SPATIAL_METHODS = {"hrtf", "panning"}
VALID_MOGRAPH_STYLES = {"bar", "circle", "dots"}

# Closed, ordered set of add-audio duration policies (first is the safe default).
# Shared by the engine, the MCP surface, and the CLI parser so there is one
# source of truth (no duplicated literal lists).
DURATION_POLICIES = ("keep_video", "loop_audio", "pad_audio", "trim_audio", "shortest")
BODY_SWAP_DURATION_POLICIES = ("pad_video", "trim_video", "trim_audio")
VALID_LAYOUTS = {"side-by-side", "top-bottom"}
VALID_HYPERFRAMES_TEMPLATES = {"blank", "warm-grain", "swiss-grid"}
VALID_HYPERFRAMES_QUALITIES = {"draft", "standard", "high"}
VALID_HYPERFRAMES_FORMATS = {"mp4", "webm", "mov", "png-sequence"}
VALID_HYPERFRAMES_RESOLUTIONS = {"landscape", "portrait", "landscape-4k", "portrait-4k", "1080p", "4k", "uhd"}
VALID_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large", "turbo"}
VALID_DEMUCS_MODELS = {"htdemucs", "htdemucs_ft", "mdx", "mdx_extra", "mdx_extra_q"}
VALID_UPSCALE_MODELS = {"realesrgan", "bsrgan"}
VALID_COLOR_GRADE_STYLES = {"auto", "warm", "cool", "vintage", "cinematic", "noir", "dramatic"}
VALID_AUDIO_SEQUENCE_TYPES = {"tone", "preset", "whoosh"}
FILTER_PARAMETER_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "blur": {"radius": (0.0, 50.0), "strength": (0.0, 5.0)},
    "sharpen": {"amount": (0.0, 3.0)},
    "brightness": {"level": (-1.0, 1.0)},
    "contrast": {"level": (0.0, 3.0)},
    "saturation": {"level": (0.0, 3.0)},
    "vignette": {"angle": (0.0, 6.2832)},
    "denoise": {
        "luma_spatial": (0.0, 30.0),
        "chroma_spatial": (0.0, 30.0),
        "luma_tmp": (0.0, 30.0),
        "chroma_tmp": (0.0, 30.0),
    },
    "ken_burns": {"zoom_speed": (0.0001, 0.01)},
    "reverb": {
        "in_gain": (0.0, 1.0),
        "out_gain": (0.0, 1.0),
        "decay": (0.0, 0.9),
    },
    "compressor": {"ratio": (1.0, 20.0)},
    "noise_reduction": {"noise_level": (-60.0, 0.0)},
}

VALID_AUDIO_PRESETS = {
    "ui-blip",
    "ui-click",
    "ui-tap",
    "ui-whoosh-up",
    "ui-whoosh-down",
    "drone-low",
    "drone-mid",
    "drone-tech",
    "drone-ominous",
    "chime-success",
    "chime-error",
    "chime-notification",
    "bass-kick",
    "snare",
    "hi-hat",
    "alarm",
    "notify",
    "confirm",
    "cancel",
    "data-flow",
    "typing",
    "scan",
    "processing",
    "upload",
    "download",
}

_CSS_COLOR_NAMES = frozenset(
    {
        "white",
        "black",
        "red",
        "green",
        "blue",
        "yellow",
        "cyan",
        "magenta",
        "orange",
        "purple",
        "pink",
        "brown",
        "gray",
        "grey",
        "silver",
        "gold",
        "navy",
        "teal",
        "maroon",
        "olive",
        "lime",
        "aqua",
        "fuchsia",
        "indigo",
        "violet",
        "coral",
        "salmon",
        "tomato",
        "khaki",
        "lavender",
        "turquoise",
        "tan",
        "wheat",
        "ivory",
        "beige",
        "linen",
        "snow",
        "mintcream",
        "azure",
        "aliceblue",
        "ghostwhite",
        "honeydew",
        "seashell",
        "whitesmoke",
        "oldlace",
        "floralwhite",
        "cornsilk",
        "lemonchiffon",
        "lightyellow",
        "lightcyan",
        "paleturquoise",
        "powderblue",
        "lightblue",
        "skyblue",
        "lightskyblue",
        "steelblue",
        "dodgerblue",
        "deepskyblue",
        "cornflowerblue",
        "royalblue",
        "mediumblue",
        "darkblue",
        "midnightblue",
        "slateblue",
        "darkslateblue",
        "mediumpurple",
        "blueviolet",
        "darkviolet",
        "darkorchid",
        "mediumorchid",
        "orchid",
        "plum",
        "mediumvioletred",
        "palevioletred",
        "hotpink",
        "deeppink",
        "lightpink",
        "rosybrown",
        "indianred",
        "firebrick",
        "darkred",
        "crimson",
        "orangered",
        "lightsalmon",
        "darksalmon",
        "lightcoral",
        "peachpuff",
        "bisque",
        "moccasin",
        "navajowhite",
        "sandybrown",
        "chocolate",
        "saddlebrown",
        "sienna",
        "burlywood",
        "peru",
        "darkgoldenrod",
        "goldenrod",
        "lightgoldenrod",
        "darkkhaki",
        "chartreuse",
        "greenyellow",
        "springgreen",
        "mediumspringgreen",
        "lawngreen",
        "darkgreen",
        "forestgreen",
        "seagreen",
        "darkseagreen",
        "lightgreen",
        "palegreen",
        "limegreen",
    }
)

_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FFMPEG_SPECIAL_CHARS = set(":=;'[]\\")

# Graphics hex-color regex (optional ``#``, 6 hex digits, optional 2 alpha).
# Distinct from the stricter ``_HEX_COLOR_RE`` used by ``_validate_color`` — the
# graphics pipeline rejects the 3-digit short form to keep receipt determinism
# stable across color-formatting variations.
GRAPHICS_HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")

# Graphics layers must be exact deterministic editor layers — these are the
# forbidden generative-routing fields. Closed set; adding a field requires a
# policy update so callers can never smuggle generative intent past the boundary.
GRAPHICS_GENERATIVE_FIELD_HINTS = frozenset(
    {
        "prompt",
        "model",
        "seed",
        "provider",
        "generator",
        "diffusion",
        "inpaint",
        "outpaint",
        "text_to_image",
        "image_to_image",
    }
)

# Closed field set for a graphics layer; any other key is rejected at the public
# boundary so the receipt schema stays stable and reviewable.
GRAPHICS_LAYER_BASE_FIELDS = frozenset(
    {
        "kind",
        "text",
        "color",
        "size",
        "position",
        "start",
        "duration",
        "src",
        "opacity",
        "width",
        "height",
    }
)


# --------------------------------------------------------------------------- #
# Subtitle safe-area profile data (immutable source of truth)
# --------------------------------------------------------------------------- #
#
# The numeric profile constants below — display dimensions, title-safe margin,
# subtitle font size, anchor position, and line/character constraints — are
# validation constants per AGENTS.md Rule 13.  The subtitle QA module imports
# this tuple and builds its typed ``PLATFORM_PROFILES`` dict deterministically
# from it so there is exactly one source of truth.


class SubtitleSafeAreaProfileData(NamedTuple):
    """Immutable record for one platform's subtitle safe-area constraints."""

    platform: str
    display_width: int
    display_height: int
    title_safe_margin_pct: float
    subtitle_font_size_px: int
    subtitle_anchor_x_pct: float
    subtitle_anchor_y_pct: float
    max_chars_per_line: int
    max_lines: int


#: Immutable platform safe-area profiles — the single source of truth used by
#: the deterministic subtitle safe-area QA across vertical/horizontal/square.
SUBTITLE_SAFE_AREA_PROFILES: tuple[SubtitleSafeAreaProfileData, ...] = (
    SubtitleSafeAreaProfileData(
        platform="vertical",
        display_width=1080,
        display_height=1920,
        title_safe_margin_pct=0.08,
        subtitle_font_size_px=64,
        subtitle_anchor_x_pct=0.5,
        subtitle_anchor_y_pct=0.90,
        max_chars_per_line=28,
        max_lines=3,
    ),
    SubtitleSafeAreaProfileData(
        platform="horizontal",
        display_width=1920,
        display_height=1080,
        title_safe_margin_pct=0.10,
        subtitle_font_size_px=48,
        subtitle_anchor_x_pct=0.5,
        subtitle_anchor_y_pct=0.88,
        max_chars_per_line=42,
        max_lines=3,
    ),
    SubtitleSafeAreaProfileData(
        platform="square",
        display_width=1080,
        display_height=1080,
        title_safe_margin_pct=0.08,
        subtitle_font_size_px=56,
        subtitle_anchor_x_pct=0.5,
        subtitle_anchor_y_pct=0.88,
        max_chars_per_line=36,
        max_lines=3,
    ),
)


def _validate_color(color: str) -> None:
    """Validate a color value to prevent FFmpeg filter injection.

    Accepts CSS named colors (whitelist) and hex colors (#RGB, #RRGGBB, #RRGGBBAA).
    Rejects anything containing FFmpeg special characters.
    """
    if not isinstance(color, str):
        raise MCPVideoError(
            "invalid_color: value must be a string",
            error_type="validation_error",
            code="invalid_color",
        )
    if any(c in _FFMPEG_SPECIAL_CHARS for c in color):
        raise MCPVideoError(
            "invalid_color: contains FFmpeg special characters",
            error_type="validation_error",
            code="invalid_color",
        )
    if color.lower() in _CSS_COLOR_NAMES:
        return
    if _HEX_COLOR_RE.match(color):
        return
    raise MCPVideoError(
        "invalid_color: not a recognized CSS name or hex color",
        error_type="validation_error",
        code="invalid_color",
    )


def _validate_chroma_color(color: str) -> None:
    """Validate a chroma-key color in FFmpeg 0xRRGGBB hex format.

    Ensures the value is exactly 7 characters (``0x`` prefix + 6 hex digits)
    and contains only legal hex characters to prevent FFmpeg filter injection.
    """
    if not isinstance(color, str) or len(color) != 8 or not color.startswith("0x"):
        raise MCPVideoError(
            "color must be in 0xRRGGBB format (e.g. 0x00FF00)",
            error_type="validation_error",
            code="invalid_parameter",
        )
    hex_part = color[2:]
    if not all(c in "0123456789abcdefABCDEF" for c in hex_part):
        raise MCPVideoError(
            "color must contain only hex characters (0-9, a-f, A-F) after 0x prefix",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _validate_normalized_float(
    value: float | int | str,
    name: str = "value",
    lo: float = 0.0,
    hi: float = 1.0,
) -> float:
    """Validate a float is in [lo, hi]. Returns the validated float.

    Used for opacity, similarity, blend, and other normalized parameters.
    """
    try:
        f = float(value)
    except (TypeError, ValueError) as e:
        raise MCPVideoError(
            f"{name} must be a number, got {type(value).__name__}",
            error_type="validation_error",
            code="invalid_parameter",
        ) from e
    if f < lo or f > hi:
        raise MCPVideoError(
            f"{name} must be between {lo} and {hi}, got {f}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return f


def _validate_timing_against_duration(
    start_time: float | None,
    duration: float | None,
    video_duration: float,
) -> list[str]:
    """Validate timing parameters against video duration.

    Returns list of warnings for non-fatal issues (overlay extends past end, etc.).
    """
    warnings: list[str] = []
    if start_time is not None and start_time > video_duration:
        warnings.append(
            f"start_time={start_time}s exceeds video duration ({video_duration:.2f}s). Overlay will never appear."
        )
    if start_time is not None and duration is not None:
        end = start_time + duration
        if end > video_duration:
            warnings.append(
                f"Overlay ends at {end:.2f}s, past video duration ({video_duration:.2f}s). It will disappear early."
            )
    return warnings
