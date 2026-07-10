"""Pre-merge validation guardrails."""

from __future__ import annotations

from .errors import MCPVideoError
from .models import VideoInfo


def validate_merge_compatibility(
    infos: list[VideoInfo],
    transition_duration: float = 0.0,
) -> list[str]:
    """Validate clips can be merged without silent bad output.

    Accepts already-probed VideoInfo objects to avoid double-probing.
    Returns list of warning messages.
    Raises MCPVideoError for hard failures (zero-duration clips, transition too long).
    """
    warnings: list[str] = []
    if len(infos) < 2:
        return warnings

    # 1. Check for zero-duration clips before transition math.
    for info in infos:
        if info.duration <= 0:
            raise MCPVideoError(
                f"Clip '{info.path}' has zero or negative duration ({info.duration}).",
                error_type="validation_error",
                code="invalid_duration",
            )

    # 2. Check for mixed audio / no-audio
    has_audio = [i.audio_codec is not None for i in infos]
    if any(has_audio) and not all(has_audio):
        warnings.append(
            "Merged clips have mixed audio/no-audio. "
            "Clips without audio may cause concat demuxer errors or silent output. "
            "Consider normalizing all clips to the same audio presence."
        )

    # 3. Check resolution mismatch
    resolutions = {(i.width, i.height) for i in infos}
    if len(resolutions) > 1:
        warnings.append(
            f"Clips have different resolutions: {sorted(resolutions)}. Merge will normalize by re-encoding all clips."
        )

    # 4. Check FPS mismatch
    fps_values = sorted({round(i.fps, 2) for i in infos})
    if len(fps_values) > 1:
        warnings.append(f"Clips have different frame rates: {fps_values}. Output may stutter or drop frames.")

    # 5. Check duration vs transition
    if transition_duration > 0:
        min_dur = min(i.duration for i in infos)
        if transition_duration >= min_dur:
            raise MCPVideoError(
                f"transition_duration ({transition_duration}s) must be less than "
                f"the shortest clip duration ({min_dur:.2f}s).",
                error_type="validation_error",
                code="transition_too_long",
            )
        if transition_duration > min_dur * 0.5:
            warnings.append(
                f"transition_duration ({transition_duration}s) is >50% of the shortest "
                f"clip ({min_dur:.2f}s). The transition may dominate the visual."
            )

    return warnings
