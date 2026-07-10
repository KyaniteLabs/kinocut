"""Audio mixing and overlay guardrails."""

from __future__ import annotations


from .errors import MCPVideoError
from .models import VideoInfo


def validate_audio_mix(
    source_info: VideoInfo,
    added_info: VideoInfo,
    volume: float = 1.0,
    start_time: float = 0.0,
) -> list[str]:
    """Validate audio mix parameters before execution.

    Accepts already-probed VideoInfo objects to avoid double-probing.
    Returns list of warning messages.
    Raises MCPVideoError for hard validation failures.
    """
    warnings: list[str] = []

    source_has_audio = source_info.audio_codec is not None
    added_has_audio = added_info.audio_codec is not None

    if not source_has_audio and not added_has_audio:
        warnings.append("Neither source nor added media has an audio stream.")
        return warnings

    # 1. Sample rate mismatch
    if source_has_audio and added_has_audio:
        sr_source = source_info.audio_sample_rate
        sr_added = added_info.audio_sample_rate
        if sr_source and sr_added and sr_source != sr_added:
            warnings.append(
                f"Sample rate mismatch: source={sr_source}Hz, "
                f"added={sr_added}Hz. "
                f"FFmpeg will resample but quality may degrade."
            )

    # 2. Volume clipping risk
    if volume > 1.0:
        warnings.append(
            f"volume={volume} > 1.0. If source audio is already near peak, this may cause digital clipping/distortion."
        )
    if volume < 0.0:
        raise MCPVideoError(
            f"volume must be >= 0, got {volume}",
            error_type="validation_error",
            code="invalid_volume",
        )

    # 3. Start time beyond source duration
    if source_has_audio and start_time > source_info.duration:
        warnings.append(
            f"start_time={start_time}s exceeds source duration ({source_info.duration:.2f}s). Audio will never play."
        )

    return warnings
