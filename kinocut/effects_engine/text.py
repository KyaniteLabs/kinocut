"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import os
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_SAFE_SUBTITLE_FONT_SIZE, DEFAULT_SUBTITLE_MAX_CHARS_PER_LINE, DEFAULT_SUBTITLE_MAX_LINES
from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import _sanitize_ffmpeg_number
from ..ffmpeg_helpers import (
    _validate_input_path,
    _validate_output_path,
    _run_command,
    _escape_ffmpeg_filter_value,
    _run_ffprobe_json,
)
from ..validation import _validate_color, _validate_timing_against_duration
import warnings as _warnings

logger = logging.getLogger(__name__)

VALID_TEXT_POSITIONS = {"center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"}


def _validate_text_position(position: str) -> None:
    if position not in VALID_TEXT_POSITIONS:
        raise MCPVideoError(
            f"position must be one of {sorted(VALID_TEXT_POSITIONS)}, got {position}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _wrap_subtitle_text_for_safe_area(
    text: str,
    max_chars_per_line: int = DEFAULT_SUBTITLE_MAX_CHARS_PER_LINE,
    max_lines: int = DEFAULT_SUBTITLE_MAX_LINES,
) -> str:
    """Wrap subtitle dialogue into a bounded safe-area block."""
    lines = textwrap.wrap(
        " ".join(text.split()),
        width=max_chars_per_line,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = kept[-1].rstrip(" .,:;") + "…"
        return "\n".join(kept)
    return "\n".join(lines)


def _is_subtitle_timing_line(line: str) -> bool:
    return "-->" in line


def _is_srt_index_line(line: str) -> bool:
    return line.strip().isdigit()


def _is_webvtt_metadata_block(lines: list[str]) -> bool:
    first = lines[0].strip() if lines else ""
    if first == "WEBVTT":
        return True
    if first.startswith("NOTE"):
        return True
    return first in {"STYLE", "REGION"}


def _wrap_subtitle_payload_for_safe_area(
    payload: str,
    max_chars_per_line: int = DEFAULT_SUBTITLE_MAX_CHARS_PER_LINE,
    max_lines: int = DEFAULT_SUBTITLE_MAX_LINES,
) -> str:
    """Wrap SRT/VTT dialogue lines while preserving timing/index lines."""
    blocks = payload.strip().split("\n\n")
    wrapped_blocks: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if _is_webvtt_metadata_block(lines):
            wrapped_blocks.append(block)
            continue
        header = [line for line in lines if _is_srt_index_line(line) or _is_subtitle_timing_line(line)]
        dialogue = [line for line in lines if line not in header and line.strip() and line.strip() != "WEBVTT"]
        if not dialogue:
            wrapped_blocks.append(block)
            continue
        wrapped = _wrap_subtitle_text_for_safe_area(" ".join(dialogue), max_chars_per_line, max_lines)
        wrapped_blocks.append("\n".join([*header, wrapped]))
    return "\n\n".join(wrapped_blocks) + "\n"


def _prepare_safe_subtitle_file(subtitles: str, max_chars_per_line: int) -> str:
    """Return a wrapped temp subtitle file for SRT/VTT inputs."""
    suffix = Path(subtitles).suffix.lower()
    if suffix not in {".srt", ".vtt"}:
        return subtitles
    source = Path(subtitles).read_text(encoding="utf-8")
    wrapped = _wrap_subtitle_payload_for_safe_area(source, max_chars_per_line=max_chars_per_line)
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
        tmp.write(wrapped)
        return tmp.name


def _subtitle_filter(
    prepared_subtitles: str, font: str, size: int, color: str, outline: int, outline_color: str
) -> str:
    """Build a safe subtitles filter string."""
    safe_subtitles = _escape_ffmpeg_filter_value(prepared_subtitles)
    safe_font = _escape_ffmpeg_filter_value(font)
    safe_color = _escape_ffmpeg_filter_value(color)
    safe_outline_color = _escape_ffmpeg_filter_value(outline_color)
    return (
        f"subtitles={safe_subtitles}:force_style='"
        f"FontName={safe_font},"
        f"FontSize={size},"
        f"PrimaryColour={safe_color},"
        f"OutlineColour={safe_outline_color},"
        f"Outline={outline},"
        f"BorderStyle=1'"
    )


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Return (width, height) for the first video stream."""
    try:
        info = _run_ffprobe_json(video_path)
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                return int(stream["width"]), int(stream["height"])
    except Exception as e:
        logger.warning("Could not get video dimensions, using fallback: %s", e)
    return 1920, 1080


def _load_pil_font(font_name: str, size: int):
    """Try to locate a TrueType font file for PIL."""
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    import glob
    import platform

    cleaned = font_name.replace(" ", "").replace("-", "").lower()
    paths: list[str] = []
    system = platform.system()
    if system == "Darwin":
        paths = [
            "/System/Library/Fonts/**/*.ttf",
            "/System/Library/Fonts/**/*.ttc",
            "/Library/Fonts/**/*.ttf",
            "/Library/Fonts/**/*.ttc",
            os.path.expanduser("~/Library/Fonts/**/*.ttf"),
            os.path.expanduser("~/Library/Fonts/**/*.ttc"),
        ]
    elif system == "Linux":
        paths = [
            "/usr/share/fonts/**/*.ttf",
            "/usr/local/share/fonts/**/*.ttf",
            os.path.expanduser("~/.fonts/**/*.ttf"),
        ]
    elif system == "Windows":
        paths = ["C:/Windows/Fonts/*.ttf", "C:/Windows/Fonts/*.ttc"]

    for pattern in paths:
        for path in glob.glob(pattern, recursive=True):
            base = os.path.splitext(os.path.basename(path))[0].replace(" ", "").replace("-", "").lower()
            if cleaned in base or base in cleaned:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        try:
            return ImageFont.truetype(f"{font_name}.ttf", size)
        except OSError:
            return None


def _measure_text(text: str, font_name: str, size: int) -> tuple[int, int]:
    """Measure text width/height in pixels. Falls back to heuristic."""
    try:
        font_obj = _load_pil_font(font_name, size)
        if font_obj is not None:
            bbox = font_obj.getbbox(text)
            if bbox:
                return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    except Exception as e:
        logger.warning("PIL text measurement failed, using fallback: %s", e)
    lines = text.split("\n")
    max_chars = max((len(line) for line in lines), default=0)
    width = int(max_chars * size * 0.55)
    height = int(len(lines) * size * 1.2)
    return width, height


def _text_position_xy(position: str, video_w: int, video_h: int, text_w: int, text_h: int) -> tuple[int, int]:
    """Compute top-left (x, y) for text given position keyword."""
    pos_map = {
        "center": ((video_w - text_w) // 2, (video_h - text_h) // 2),
        "top": ((video_w - text_w) // 2, 20),
        "bottom": ((video_w - text_w) // 2, video_h - text_h - 20),
        "top-left": (20, 20),
        "top-right": (video_w - text_w - 20, 20),
        "bottom-left": (20, video_h - text_h - 20),
        "bottom-right": (video_w - text_w - 20, video_h - text_h - 20),
    }
    return pos_map.get(position, pos_map["center"])


def _escape_sendcmd_value(value: str) -> str:
    """Escape a value for use inside single quotes in a sendcmd file."""
    # Re-use the same escaping rules as FFmpeg filter values since
    # sendcmd forwards the text directly into drawtext reinit.
    return _escape_ffmpeg_filter_value(value)


def _drawtext_font_option(font: str | None) -> str:
    """Return a drawtext font option that works for both font names and paths."""
    if font and os.path.exists(font):
        return f"fontfile={_escape_ffmpeg_filter_value(font)}"
    safe_font = _escape_ffmpeg_filter_value(font or "Arial")
    return f"font={safe_font}"


def _build_typewriter_filter(
    text: str,
    font: str,
    size: int,
    color: str,
    position: str,
    start: float,
    duration: float,
    typewriter_speed: float,
    video: str,
) -> tuple[str, str]:
    """Build a filter chain and sendcmd file for character-by-character reveal.

    Returns:
        (filter_complex, cmd_file_path)
    """
    video_w, video_h = _get_video_dimensions(video)
    text_w, text_h = _measure_text(text, font, size)
    text_x, text_y = _text_position_xy(position, video_w, video_h, text_w, text_h)

    char_count = len(text)
    if char_count == 0:
        return "", ""

    safe_start = _sanitize_ffmpeg_number(start, "start")
    safe_duration = _sanitize_ffmpeg_number(duration, "duration")
    safe_speed = _sanitize_ffmpeg_number(typewriter_speed, "typewriter_speed")
    char_duration = max(0.01, safe_speed)
    end_time = safe_start + safe_duration

    font_option = _drawtext_font_option(font)
    safe_color = _escape_ffmpeg_filter_value(color) if color is not None else color
    safe_size = int(_sanitize_ffmpeg_number(size, "size"))
    safe_text_x = int(_sanitize_ffmpeg_number(text_x, "text_x"))
    safe_text_y = int(_sanitize_ffmpeg_number(text_y, "text_y"))

    # Build sendcmd commands: start empty, then reveal one more char at each step
    cmd_lines = [f"{safe_start:.4f} drawtext@1 reinit text='{_escape_sendcmd_value('')}'"]
    for i in range(1, char_count + 1):
        t_cmd = safe_start + i * char_duration
        partial = text[:i]
        safe_partial = _escape_sendcmd_value(partial)
        cmd_lines.append(f"{t_cmd:.4f} drawtext@1 reinit text='{safe_partial}'")

    cmd_content = ";\n".join(cmd_lines) + ";"

    cmd_fd, cmd_path = tempfile.mkstemp(suffix=".txt", prefix="mcp_video_typewriter_")
    try:
        with os.fdopen(cmd_fd, "w", encoding="utf-8") as f:
            f.write(cmd_content)
    except Exception:
        os.close(cmd_fd)
        if os.path.exists(cmd_path):
            os.unlink(cmd_path)
        raise

    safe_cmd_path = _escape_ffmpeg_filter_value(cmd_path)
    filter_complex = (
        f"sendcmd=f={safe_cmd_path},"
        f"drawtext@1=text='':{font_option}:fontsize={safe_size}:fontcolor={safe_color}:"
        f"x={safe_text_x}:y={safe_text_y}:enable='between(t\\,{safe_start}\\,{end_time})'"
    )
    return filter_complex, cmd_path


def _build_fade_filter(
    text: str,
    font: str,
    size: int,
    color: str,
    position: str,
    start: float,
    duration: float,
    video: str,
    **_kw: Any,
) -> tuple[str, str]:
    """Build fade-in / fade-out drawtext filter."""
    safe_text = _escape_ffmpeg_filter_value(text)
    font_option = _drawtext_font_option(font)
    safe_color = _escape_ffmpeg_filter_value(color) if color is not None else color
    pos_map = {
        "center": "(w-text_w)/2:(h-text_h)/2",
        "top": "(w-text_w)/2:20",
        "bottom": "(w-text_w)/2:h-text_h-20",
        "top-left": "20:20",
        "top-right": "w-text_w-20:20",
        "bottom-left": "20:h-text_h-20",
        "bottom-right": "w-text_w-20:h-text_h-20",
    }
    pos = pos_map.get(position, pos_map["center"])
    fade_start = start
    fade_end = start + 0.5
    fade_out_start = start + duration - 0.5
    fade_out_end = start + duration
    alpha_expr = (
        f"if(lt(t,{fade_start}),0,"
        f"if(lt(t,{fade_end}),(t-{fade_start})/0.5,"
        f"if(lt(t,{fade_out_start}),1,"
        f"if(lt(t,{fade_out_end}),({fade_out_end}-t)/0.5,0))))"
    )
    filter_complex = (
        f"drawtext=text='{safe_text}':{font_option}:fontsize={size}:fontcolor={safe_color}:"
        f"x={pos.split(':')[0]}:y={pos.split(':')[1]}:"
        f"enable='between(t\\,{start}\\,{start + duration})':"
        f"alpha='{alpha_expr}'"
    )
    return filter_complex, ""


def _build_slide_up_filter(
    text: str,
    font: str,
    size: int,
    color: str,
    position: str,
    start: float,
    duration: float,
    video: str,
    **_kw: Any,
) -> tuple[str, str]:
    """Build slide-up drawtext filter."""
    safe_text = _escape_ffmpeg_filter_value(text)
    font_option = _drawtext_font_option(font)
    safe_color = _escape_ffmpeg_filter_value(color) if color is not None else color
    pos_map = {
        "center": "(w-text_w)/2:(h-text_h)/2",
        "top": "(w-text_w)/2:20",
        "bottom": "(w-text_w)/2:h-text_h-20",
        "top-left": "20:20",
        "top-right": "w-text_w-20:20",
        "bottom-left": "20:h-text_h-20",
        "bottom-right": "w-text_w-20:h-text_h-20",
    }
    pos = pos_map.get(position, pos_map["center"])
    x_expr, y_expr = pos.split(":")
    # Animate the slide-up by offsetting the RESOLVED y for every position (start
    # 50px lower, ease to target over 0.3s). The old code string-replaced the
    # center-only "(h-text_h)/2" literal, so the other 6 positions rendered static.
    y_offset = f"+50*(1-min(1\\,(t-{start})/0.3))"
    y_expr = f"({y_expr}){y_offset}"
    filter_complex = (
        f"drawtext=text='{safe_text}':{font_option}:fontsize={size}:fontcolor={safe_color}:"
        f"x={x_expr}:y={y_expr}:"
        f"enable='between(t\\,{start}\\,{start + duration})':"
        f"alpha='1'"
    )
    return filter_complex, ""


def _build_glitch_filter(
    text: str,
    font: str,
    size: int,
    color: str,
    position: str,
    start: float,
    duration: float,
    video: str,
    **_kw: Any,
) -> tuple[str, str]:
    """Build glitch-style drawtext filter."""
    safe_text = _escape_ffmpeg_filter_value(text)
    font_option = _drawtext_font_option(font)
    safe_color = _escape_ffmpeg_filter_value(color) if color is not None else color
    pos_map = {
        "center": "(w-text_w)/2:(h-text_h)/2",
        "top": "(w-text_w)/2:20",
        "bottom": "(w-text_w)/2:h-text_h-20",
        "top-left": "20:20",
        "top-right": "w-text_w-20:20",
        "bottom-left": "20:h-text_h-20",
        "bottom-right": "w-text_w-20:h-text_h-20",
    }
    pos = pos_map.get(position, pos_map["center"])
    alpha_expr = "if(random(0)*lt(mod(t,0.2),0.1),0.8,1)"
    filter_complex = (
        f"drawtext=text='{safe_text}':{font_option}:fontsize={size}:fontcolor={safe_color}:"
        f"x={pos.split(':')[0]}:y={pos.split(':')[1]}:"
        f"enable='between(t\\,{start}\\,{start + duration})':"
        f"alpha='{alpha_expr}'"
    )
    return filter_complex, ""


_ANIMATION_STRATEGIES: dict[str, Callable[..., tuple[str, str]]] = {
    "fade": _build_fade_filter,
    "slide-up": _build_slide_up_filter,
    "glitch": _build_glitch_filter,
    "typewriter": _build_typewriter_filter,
}


def text_animated(
    video: str,
    text: str,
    output: str,
    animation: str = "fade",
    font: str = "Arial",
    size: int = 48,
    color: str = "white",
    position: str = "center",
    start: float = 0,
    duration: float = 3.0,
    typewriter_speed: float = 0.08,
) -> str:
    """Add animated text to video.

    Args:
        video: Input video path
        text: Text to display
        output: Output video path
        animation: "fade", "slide-up", "typewriter", "glitch"
        font: Font family
        size: Font size
        color: Text color
        position: Text position
        start: Start time in seconds
        duration: Display duration
        typewriter_speed: Seconds per character for typewriter animation

    Returns:
        Path to output video
    """
    if not text or not text.strip():
        raise MCPVideoError("Text cannot be empty", error_type="validation_error", code="invalid_parameter")
    _validate_text_position(position)

    video = _validate_input_path(video)
    _validate_output_path(output)

    strategy = _ANIMATION_STRATEGIES.get(animation)
    if strategy is None:
        raise MCPVideoError(
            f"animation must be one of {sorted(_ANIMATION_STRATEGIES)}, got {animation}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    # --- Guardrails: timing + color validation ---
    _validate_color(color)
    if start < 0:
        raise MCPVideoError(
            f"start must be >= 0, got {start}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if duration <= 0:
        raise MCPVideoError(
            f"duration must be > 0, got {duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    try:
        video_w, video_h = _get_video_dimensions(video)
        from ..engine_probe import probe as _probe

        vid_info = _probe(video)
        timing_warnings = _validate_timing_against_duration(start, duration, vid_info.duration)
        for w in timing_warnings:
            _warnings.warn(f"[TEXT GUARDRAIL] {w}", stacklevel=2)
        # Text overflow check
        text_w, text_h = _measure_text(text, font, size)
        if text_w > video_w - 40 or text_h > video_h - 40:
            _warnings.warn(
                f"[TEXT GUARDRAIL] Text dimensions ({text_w}x{text_h}) may exceed "
                f"video frame ({video_w}x{video_h}). "
                f"Consider reducing font size or shortening text.",
                stacklevel=2,
            )
    except MCPVideoError:
        raise
    except Exception as e:
        message = f"[TEXT GUARDRAIL] Could not validate text layout: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=2)
    # --- End guardrails ---

    filter_complex, cmd_path = strategy(
        text=text,
        font=font,
        size=size,
        color=color,
        position=position,
        start=start,
        duration=duration,
        video=video,
        typewriter_speed=typewriter_speed,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video,
        "-vf",
        filter_complex,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    try:
        _run_command(cmd)
    finally:
        if cmd_path:
            Path(cmd_path).unlink(missing_ok=True)

    return output


def text_subtitles(
    video: str,
    subtitles: str,
    output: str,
    style: dict[str, Any] | None = None,
) -> str:
    """Burn subtitles from SRT/VTT into video with styling.

    Args:
        video: Input video path
        subtitles: Subtitle file path (SRT or VTT)
        output: Output video path
        style: Style dict with keys:
            - font, size, color, outline, outline_color, background, position

    Returns:
        Path to output video
    """
    video = _validate_input_path(video)
    _validate_output_path(output)

    if not os.path.isfile(subtitles):
        raise InputFileError(f"Subtitles file not found: {subtitles}")

    style = style or {}

    # Build subtitle filter options
    font = style.get("font", "Arial")
    unsafe_layout = bool(style.get("allow_unsafe_layout", False))
    size = int(style.get("size", DEFAULT_SAFE_SUBTITLE_FONT_SIZE))
    if not unsafe_layout:
        size = min(size, DEFAULT_SAFE_SUBTITLE_FONT_SIZE)
    color = style.get("color", "white")
    outline = style.get("outline", 2)
    outline_color = style.get("outline_color", "black")
    max_chars_per_line = max(20, min(80, int(style.get("max_chars_per_line", DEFAULT_SUBTITLE_MAX_CHARS_PER_LINE))))

    # Convert hex colors to FFmpeg format
    if color.startswith("#"):
        color = f"0x{color[1:]}"
    if outline_color.startswith("#"):
        outline_color = f"0x{outline_color[1:]}"

    prepared_subtitles = _prepare_safe_subtitle_file(subtitles, max_chars_per_line)
    filter_complex = _subtitle_filter(prepared_subtitles, font, size, color, outline, outline_color)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video,
        "-vf",
        filter_complex,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    try:
        _run_command(cmd)
    finally:
        if prepared_subtitles != subtitles:
            Path(prepared_subtitles).unlink(missing_ok=True)

    return output


# ---------------------------------------------------------------------------
# Motion Graphics
# ---------------------------------------------------------------------------
