"""Designed silence rendering."""

from __future__ import annotations

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import DEFAULT_SAMPLE_RATE_HZ, silence_wav, synthesize_tone
from kinocut_sound.script_parser import SilenceQuality


def render_silence(
    *,
    duration_seconds: float,
    quality: SilenceQuality | str = SilenceQuality.DEAD,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> bytes:
    """Render designed silence. Room-tone is a very low-amplitude noise floor tone."""

    if duration_seconds <= 0:
        raise mix_error("silence duration must be positive", MIX_INPUT_INVALID)
    q = quality.value if isinstance(quality, SilenceQuality) else str(quality)
    if q in {"dead", "held_breath"}:
        return silence_wav(duration_seconds=duration_seconds, sample_rate_hz=sample_rate_hz)
    if q == "room_tone":
        return synthesize_tone(
            duration_seconds=duration_seconds,
            sample_rate_hz=sample_rate_hz,
            frequency_hz=60.0,
            amplitude=0.01,
            seed=7,
        )
    raise mix_error(f"unknown silence quality {q}", MIX_INPUT_INVALID)
