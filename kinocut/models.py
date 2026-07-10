"""Pydantic models for Kinocut operations."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from .defaults import DEFAULT_CRF
from .errors import MCPVideoError as _MCPVideoError


# --- Helpers ---


def _render_ascii_waveform(peaks: list[dict], width: int = 60, height: int = 10) -> str:
    """Render an ASCII waveform from peak data.

    Returns a multi-line string where each line is a time slice and the
    bar height represents the audio level at that point.
    """
    if not peaks:
        return ""
    levels = [p["level"] for p in peaks]
    min_l = min(levels)
    max_l = max(levels)
    if max_l == min_l:
        max_l = min_l + 1
    chars = " ▁▂▃▄▅▆▇█"
    step = (max_l - min_l) / (len(chars) - 1)
    idxs = [min(len(chars) - 1, max(0, int((lvl - min_l) / step))) for lvl in levels]
    lines: list[str] = []
    for h in range(height, 0, -1):
        threshold = (h - 1) / height * (len(chars) - 1)
        line = "".join(chars[min(len(chars) - 1, max(0, i - int(threshold)))] for i in idxs)
        lines.append(line)
    return "\n".join(lines)


# --- Video metadata ---


class VideoInfo(BaseModel):
    """Metadata about a video file."""

    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    bitrate: int | None = None
    size_bytes: int | None = None
    format: str | None = None
    rotation: int = 0

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def display_width(self) -> int:
        """Width accounting for rotation (e.g. 90° rotates dimensions)."""
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        """Height accounting for rotation (e.g. 90° rotates dimensions)."""
        return self.width if self.rotation in (90, 270) else self.height

    @property
    def display_resolution(self) -> str:
        return f"{self.display_width}x{self.display_height}"

    @property
    def aspect_ratio(self) -> str:
        from math import gcd

        g = gcd(self.display_width, self.display_height)
        if g == 0:
            return "unknown"
        return f"{self.display_width // g}:{self.display_height // g}"

    @property
    def size_mb(self) -> float | None:
        if self.size_bytes is not None:
            return round(self.size_bytes / (1024 * 1024), 2)
        return None


# --- Operation results ---


class EditResult(BaseModel):
    """Result of a video editing operation."""

    success: bool = True
    output_path: str
    duration: float | None = None
    resolution: str | None = None
    size_mb: float | None = None
    format: str | None = None
    operation: str | None = None
    progress: float | None = Field(default=None, description="Final progress percentage (0-100)")
    thumbnail_base64: str | None = Field(default=None, description="Base64-encoded JPEG thumbnail of the first frame")
    elapsed_ms: float | None = Field(default=None, description="Wall-clock processing time in milliseconds")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal guardrail warnings for agent workflows")
    intermediates: list[str] = Field(default_factory=list, description="Intermediate files that were cleaned up")


class ErrorResult(BaseModel):
    """Structured error result returned to agents."""

    success: Literal[False] = False
    error: dict[str, Any]


class StoryboardResult(EditResult):
    """Result of storyboard generation."""

    output_path: str = Field(default="", description="Path to storyboard grid when available, otherwise first frame")
    frames: list[str] = Field(description="Paths to extracted frame images")
    grid: str | None = Field(default=None, description="Path to storyboard grid image")
    count: int

    def model_post_init(self, __context: Any) -> None:
        if not self.output_path:
            object.__setattr__(self, "output_path", self.grid or (self.frames[0] if self.frames else ""))
        if self.operation is None:
            object.__setattr__(self, "operation", "storyboard")


class SubtitleResult(EditResult):
    """Result of subtitle generation."""

    output_path: str = Field(default="", description="Path to generated video when burned, otherwise generated SRT")
    srt_path: str | None = Field(default=None, description="Path to generated SRT file")
    video_path: str | None = Field(default=None, description="Path to burned-in video (if burn=True)")
    entry_count: int

    def model_post_init(self, __context: Any) -> None:
        if not self.output_path:
            object.__setattr__(self, "output_path", self.video_path or self.srt_path or "")
        if self.operation is None:
            object.__setattr__(self, "operation", "generate_subtitles")


class WaveformResult(BaseModel):
    """Result of audio waveform extraction.

    The synthetic field indicates whether the peak data was synthetically
    generated due to astats filter failure (True) or extracted from actual
    audio analysis (False).
    """

    success: bool = True
    duration: float
    peaks: list[dict] = Field(description="List of {time, level} data points")
    mean_level: float
    max_level: float
    min_level: float
    silence_regions: list[dict] = Field(description="List of {start, end} silence regions")
    synthetic: bool = Field(
        default=False, description="True if data was synthetically generated due to analysis failure"
    )
    text: str = Field(default="", description="ASCII waveform representation for agents")

    def model_post_init(self, __context: Any) -> None:
        if not self.text and self.peaks:
            object.__setattr__(self, "text", _render_ascii_waveform(self.peaks))


class SceneDetectionResult(BaseModel):
    """Result of scene detection."""

    success: bool = True
    scenes: list[dict] = Field(description="List of {start, end, start_frame, end_frame} dicts")
    scene_count: int
    duration: float


class ImageSequenceResult(BaseModel):
    """Result of image sequence operations."""

    success: bool = True
    frame_paths: list[str] = Field(description="Paths to extracted/generated frame images")
    frame_count: int
    fps: float


class QualityMetricsResult(BaseModel):
    """Result of quality comparison between two videos."""

    success: bool = True
    metrics: dict[str, float] = Field(description="Metric scores, e.g. {'psnr': 42.5, 'ssim': 0.95}")
    overall_quality: str = Field(description="Quality assessment: high, medium, or low")


class MetadataResult(BaseModel):
    """Result of metadata read operation."""

    success: bool = True
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    comment: str | None = None
    date: str | None = None
    tags: dict[str, str] = Field(default_factory=dict, description="All metadata tags")


class ThumbnailResult(EditResult):
    """Result of thumbnail extraction."""

    output_path: str = Field(default="", description="Alias of frame_path for agent chaining")
    frame_path: str
    timestamp: float

    def model_post_init(self, __context: Any) -> None:
        if not self.output_path:
            object.__setattr__(self, "output_path", self.frame_path)
        if self.operation is None:
            object.__setattr__(self, "operation", "thumbnail")


# --- Quality settings ---

QualityLevel = Literal["low", "medium", "high", "ultra"]

# Derive quality presets from the canonical default CRF
QUALITY_PRESETS: dict[QualityLevel, dict[str, Any]] = {
    "low": {"crf": DEFAULT_CRF + 12, "preset": "fast", "max_height": 480},
    "medium": {"crf": DEFAULT_CRF + 5, "preset": "medium", "max_height": 720},
    "high": {"crf": DEFAULT_CRF, "preset": "slow", "max_height": 1080},
    "ultra": {"crf": DEFAULT_CRF - 5, "preset": "veryslow", "max_height": 1080},
}

PREVIEW_PRESETS: dict[str, Any] = {
    "crf": 35,
    "preset": "ultrafast",
    "scale_factor": 4,  # 1/4 resolution
}

# --- Aspect ratio presets ---

ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
    "4:5": (1080, 1350),
    "21:9": (2560, 1080),
}

# --- Text positioning ---

NamedPosition = Literal[
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]

# Position can be a named position string, pixel coordinates, or percentage coordinates
Position = NamedPosition | dict[str, float]
VALID_NAMED_POSITIONS = set(get_args(NamedPosition))

# --- Transition types ---

TransitionType = Literal["fade", "dissolve", "wipe-left", "wipe-right", "wipe-up", "wipe-down"]

# --- Filter types ---

FilterType = Literal[
    "blur",
    "sharpen",
    "brightness",
    "contrast",
    "saturation",
    "grayscale",
    "sepia",
    "invert",
    "vignette",
    "color_preset",
    "denoise",
    "deinterlace",
    "ken_burns",
    "reverb",
    "compressor",
    "pitch_shift",
    "noise_reduction",
]

ColorPreset = Literal["warm", "cool", "vintage", "cinematic", "noir"]

# --- Split layout ---

SplitLayout = Literal["side-by-side", "top-bottom"]

# --- Format types ---

ExportFormat = Literal["mp4", "webm", "gif", "mov", "hevc", "av1", "prores"]

# --- Timeline DSL models ---


class TimelineClip(BaseModel):
    """A single clip in a timeline track."""

    source: str
    start: float = 0.0
    duration: float | None = None
    trim_start: float = 0.0
    trim_end: float | None = None
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0


class TimelineTransition(BaseModel):
    """A transition between two clips."""

    after_clip: int
    type: TransitionType = "fade"
    duration: float = 1.0


class TimelineTextElement(BaseModel):
    """A text overlay element in a timeline."""

    text: str
    start: float = 0.0
    duration: float | None = None
    position: Position = "top-center"
    style: dict[str, Any] = Field(
        default_factory=lambda: {
            "font": "Arial",
            "size": 48,
            "color": "white",
            "shadow": True,
        }
    )


class TimelineImageOverlay(BaseModel):
    """An image overlay element in a timeline."""

    source: str
    position: Position = "center"
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    opacity: float = 1.0
    start: float = 0.0
    duration: float | None = None


class TimelineTrack(BaseModel):
    """A track in the timeline (video, audio, text, or image)."""

    type: Literal["video", "audio", "text", "image"]
    clips: list[TimelineClip] = Field(default_factory=list)
    transitions: list[TimelineTransition] = Field(default_factory=list)
    elements: list[TimelineTextElement] = Field(default_factory=list)
    images: list[TimelineImageOverlay] = Field(default_factory=list)


class TimelineExport(BaseModel):
    """Export settings for a timeline render."""

    format: ExportFormat = "mp4"
    quality: QualityLevel = "high"


class Timeline(BaseModel):
    """Full timeline specification for complex edits."""

    width: int = 1920
    height: int = 1080
    duration: float | None = None
    tracks: list[TimelineTrack] = Field(default_factory=list)
    export: TimelineExport = Field(default_factory=TimelineExport)


# --- Watermark settings ---


class WatermarkSettings(BaseModel):
    """Settings for watermark overlay."""

    image_path: str
    position: Position = "bottom-right"
    opacity: float = 0.7
    margin: int = 20


# --- Position helpers ---


def _validate_position(position: Position) -> None:
    """Validate named and dict positions before building FFmpeg expressions."""
    if not isinstance(position, dict):
        if position not in VALID_NAMED_POSITIONS:
            raise _MCPVideoError(
                f"position must be one of {sorted(VALID_NAMED_POSITIONS)}, got {position}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        return
    if "x_pct" in position and "y_pct" in position:
        for key in ("x_pct", "y_pct"):
            val = position[key]
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise _MCPVideoError(
                    (
                        f"Invalid position: {position}. "
                        "Must be a named position (top-left, top-center, etc.) "
                        "or a dict with 'x'/'y' keys"
                    ),
                    error_type="validation_error",
                    code="invalid_parameter",
                )
            if not (0.0 <= float(val) <= 1.0):
                raise _MCPVideoError(
                    (
                        f"Invalid position: {position}. "
                        "Must be a named position (top-left, top-center, etc.) "
                        "or a dict with 'x'/'y' keys"
                    ),
                    error_type="validation_error",
                    code="invalid_parameter",
                )
    elif "x" in position and "y" in position:
        for key in ("x", "y"):
            val = position[key]
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise _MCPVideoError(
                    (
                        f"Invalid position: {position}. "
                        "Must be a named position (top-left, top-center, etc.) "
                        "or a dict with 'x'/'y' keys"
                    ),
                    error_type="validation_error",
                    code="invalid_parameter",
                )
    else:
        raise _MCPVideoError(
            "Position dict must have 'x'+'y' (pixels) or 'x_pct'+'y_pct' (percentage)",
            code="invalid_position_dict",
        )


def _position_coords(position: Position, width: int = 0, height: int = 0) -> str:
    """Return drawtext x,y expression for a named position or dict coords.

    Accepts:
    - Named positions: "top-left", "top-center", etc.
    - Pixel coordinates: {"x": 100, "y": 50}
    - Percentage: {"x_pct": 0.5, "y_pct": 0.5}
    """
    _validate_position(position)
    if isinstance(position, dict):
        if "x_pct" in position and "y_pct" in position:
            x_pct = position["x_pct"]
            y_pct = position["y_pct"]
            return f"x=w*{x_pct}-text_w/2:y=h*{y_pct}-text_h/2"
        elif "x" in position and "y" in position:
            return f"x={position['x']}:y={position['y']}"
        else:
            raise _MCPVideoError(
                "Position dict must have 'x'+'y' (pixels) or 'x_pct'+'y_pct' (percentage)",
                code="invalid_position_dict",
            )

    # These expressions use FFmpeg's text_w/text_h variables
    mapping: dict[NamedPosition, str] = {
        "top-left": "x=10:y=10",
        "top-center": "x=(w-text_w)/2:y=10",
        "top-right": "x=w-text_w-10:y=10",
        "center-left": "x=10:y=(h-text_h)/2",
        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
        "center-right": "x=w-text_w-10:y=(h-text_h)/2",
        "bottom-left": "x=10:y=h-text_h-10",
        "bottom-center": "x=(w-text_w)/2:y=h-text_h-10",
        "bottom-right": "x=w-text_w-10:y=h-text_h-10",
    }
    return mapping[position]


def _resolve_position(
    position: Position,
    position_map: dict[NamedPosition, str],
    default: NamedPosition = "center",
) -> str:
    """Resolve a Position (named or dict) to an FFmpeg overlay coordinate string.

    Used by watermark, overlay_video, and similar overlay-based operations.
    """
    _validate_position(position)
    if isinstance(position, dict):
        if "x_pct" in position and "y_pct" in position:
            x_pct = position["x_pct"]
            y_pct = position["y_pct"]
            return f"(main_w*{x_pct}-overlay_w/2):(main_h*{y_pct}-overlay_h/2)"
        elif "x" in position and "y" in position:
            return f"{position['x']}:{position['y']}"
        else:
            raise _MCPVideoError(
                "Position dict must have 'x'+'y' (pixels) or 'x_pct'+'y_pct' (percentage)",
                code="invalid_position_dict",
            )
    return position_map[position]
