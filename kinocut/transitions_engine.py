"""Video transition effects using FFmpeg."""

from .ffmpeg_helpers import _validate_input_path, _run_command, _get_video_duration, _escape_ffmpeg_filter_value
from .errors import MCPVideoError


def transition_glitch(
    clip1: str,
    clip2: str,
    output: str,
    duration: float = 0.5,
    intensity: float = 0.3,
) -> str:
    """Glitch transition using RGB shift and noise.

    Args:
        clip1: First video clip path
        clip2: Second video clip path
        output: Output video path
        duration: Transition duration in seconds
        intensity: Glitch intensity 0-1

    Returns:
        Path to output video
    """
    clip1 = _validate_input_path(clip1)
    clip2 = _validate_input_path(clip2)

    if duration <= 0:
        raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")
    if not (0.0 <= intensity <= 1.0):
        raise MCPVideoError("intensity must be 0-1", error_type="validation_error", code="invalid_parameter")

    # Get duration of first clip to calculate offset
    clip1_duration = _get_video_duration(clip1)
    offset = clip1_duration - duration

    # Ensure offset is not negative
    if offset < 0:
        offset = 0

    # Calculate intensity-based parameters
    # Intensity 0-1 maps to RGB shift of 0-20 pixels
    rgb_shift = int(intensity * 20)
    noise_amount = int(intensity * 10)

    # Use rgbashift filter for RGB channel shifting
    # More reliable than geq which has complex escaping requirements.
    # Both stages are timeline-gated with enable=between(t,offset,end) so the
    # glitch only appears during the transition window — without this the
    # RGB-shift/noise bleed across the entire merged clip.
    safe_duration = _escape_ffmpeg_filter_value(str(duration))
    safe_offset = _escape_ffmpeg_filter_value(str(offset))
    safe_rgb_shift = _escape_ffmpeg_filter_value(str(rgb_shift))
    safe_noise_amount = _escape_ffmpeg_filter_value(str(noise_amount))
    end = offset + duration
    gate = f"enable='between(t,{offset:.4f},{end:.4f})'"
    filter_complex = (
        f"[0:v][1:v]xfade=transition=fade:duration={safe_duration}:offset={safe_offset}[faded];"
        f"[faded]rgbashift=rh={safe_rgb_shift}:gh=0:bh=-{safe_rgb_shift}:ah=0:{gate}[rgbshift];"
        f"[rgbshift]noise=alls={safe_noise_amount}:allf=t+u:{gate}[glitched]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        clip1,
        "-i",
        clip2,
        "-filter_complex",
        filter_complex,
        "-map",
        "[glitched]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output,
    ]

    _run_command(cmd)

    return output


def transition_pixelate(
    clip1: str,
    clip2: str,
    output: str,
    duration: float = 0.4,
    pixel_size: int = 50,
) -> str:
    """Pixel dissolve transition using scale filter.

    Creates a transition where the video pixelates during the crossfade,
    with the pixelation peaking at the middle of the transition.

    Args:
        clip1: First video clip path
        clip2: Second video clip path
        output: Output video path
        duration: Transition duration in seconds
        pixel_size: Maximum pixel size during transition

    Returns:
        Path to output video
    """
    clip1 = _validate_input_path(clip1)
    clip2 = _validate_input_path(clip2)

    if pixel_size < 2:
        raise MCPVideoError("pixel_size must be at least 2", error_type="validation_error", code="invalid_parameter")
    if duration <= 0:
        raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")

    # Get duration of first clip to calculate offset
    clip1_duration = _get_video_duration(clip1)
    offset = clip1_duration - duration

    # Ensure offset is not negative
    if offset < 0:
        offset = 0

    # Calculate transition midpoint
    mid = offset + duration / 2

    # Pixelation effect via the dedicated `pixelize` filter, timeline-gated to the
    # transition window with `enable=between(t,...)`.
    #
    # The previous implementation animated a per-frame `scale=...:eval=frame`, which
    # forced swscale to reconfigure its context every frame and was pathologically
    # slow — a 2s clip exceeded the 600s FFmpeg timeout. `pixelize` is a single fast
    # pass and is identity outside the enabled window, so the cost is bounded to the
    # short transition. Two stacked `pixelize` passes — a base block across the whole
    # transition window and a larger block over the inner window centred on the
    # midpoint — give a "grow to peak" pixelation feel without per-frame eval.
    safe_duration = _escape_ffmpeg_filter_value(str(duration))
    safe_offset = _escape_ffmpeg_filter_value(str(offset))

    end = offset + duration
    inner_half = duration * 0.2
    inner_start = max(offset, mid - inner_half)
    inner_end = min(end, mid + inner_half)
    # pixelize block size in pixels; pixel_size is the peak. Keep >= 2 and within
    # a sane upper bound so the block never swallows the whole frame.
    peak_block = max(2, min(int(pixel_size), 256))
    base_block = max(2, peak_block // 3)

    def _t(value: float) -> str:
        return f"{value:.4f}"

    filter_complex = (
        f"[0:v][1:v]xfade=transition=fade:duration={safe_duration}:offset={safe_offset}[faded];"
        f"[faded]pixelize=w={base_block}:h={base_block}:enable='between(t,{_t(offset)},{_t(end)})',"
        f"pixelize=w={peak_block}:h={peak_block}:enable='between(t,{_t(inner_start)},{_t(inner_end)})'[output]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        clip1,
        "-i",
        clip2,
        "-filter_complex",
        filter_complex,
        "-map",
        "[output]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output,
    ]

    _run_command(cmd)

    return output


def transition_morph(
    clip1: str,
    clip2: str,
    output: str,
    duration: float = 0.6,
    mesh_size: int = 10,
) -> str:
    """Mesh warp morph transition using pixelization effect.

    Creates a morph-like transition using FFmpeg's pixelize transition.
    The mesh_size parameter controls the intensity of the warp effect.

    Args:
        clip1: First video clip path
        clip2: Second video clip path
        output: Output video path
        duration: Transition duration in seconds
        mesh_size: Grid subdivisions (reserved for future warp intensity control)

    Returns:
        Path to output video
    """
    clip1 = _validate_input_path(clip1)
    clip2 = _validate_input_path(clip2)

    if duration <= 0:
        raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")
    if mesh_size < 2:
        raise MCPVideoError("mesh_size must be at least 2", error_type="validation_error", code="invalid_parameter")

    # Get duration of first clip to calculate offset
    clip1_duration = _get_video_duration(clip1)
    offset = clip1_duration - duration

    # Ensure offset is not negative
    if offset < 0:
        offset = 0

    # Use xfade with pixelize transition for morph-like effect
    # pixelize creates a blocky dissolve that simulates mesh morphing
    safe_duration = _escape_ffmpeg_filter_value(str(duration))
    safe_offset = _escape_ffmpeg_filter_value(str(offset))
    filter_complex = f"[0:v][1:v]xfade=transition=pixelize:duration={safe_duration}:offset={safe_offset}[output]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        clip1,
        "-i",
        clip2,
        "-filter_complex",
        filter_complex,
        "-map",
        "[output]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output,
    ]

    _run_command(cmd)

    return output
