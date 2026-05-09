"""Shared validation constants and functions for mcp-video."""

from __future__ import annotations

import re

from .errors import MCPVideoError
from .limits import *  # noqa: F403 — re-export all limit constants

VALID_FORMATS = {"mp4", "webm", "gif", "mov", "hevc", "av1", "prores"}
VALID_AUDIO_FORMATS = {"mp3", "aac", "wav", "ogg", "flac"}
VALID_PRESETS = {"ultrafast", "fast", "medium", "slow", "veryslow"}
VALID_CODECS = {"h264", "h265", "vp8", "vp9", "prores", "gif"}
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
VALID_WAVEFORMS = {"sine", "square", "sawtooth", "triangle", "noise"}
VALID_AUDIO_EFFECT_TYPES = {"lowpass", "highpass", "reverb", "normalize", "fade"}
VALID_SPATIAL_METHODS = {"hrtf", "panning"}
VALID_MOGRAPH_STYLES = {"bar", "circle", "dots"}
VALID_LAYOUTS = {"side-by-side", "top-bottom"}
VALID_HYPERFRAMES_TEMPLATES = {"blank", "warm-grain", "swiss-grid"}
VALID_HYPERFRAMES_QUALITIES = {"draft", "standard", "high"}
VALID_HYPERFRAMES_FORMATS = {"mp4", "webm", "mov", "png-sequence"}
VALID_HYPERFRAMES_RESOLUTIONS = {"landscape", "portrait", "landscape-4k", "portrait-4k", "1080p", "4k", "uhd"}
VALID_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large", "turbo"}
VALID_DEMUCS_MODELS = {"htdemucs", "htdemucs_ft", "mdx", "mdx_extra", "mdx_extra_q"}
VALID_UPSCALE_MODELS = {"realesrgan", "bsrgan"}
VALID_COLOR_GRADE_STYLES = {"auto", "warm", "cool", "vintage", "cinematic", "noir"}
VALID_AUDIO_SEQUENCE_TYPES = {"tone", "preset", "whoosh"}
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
