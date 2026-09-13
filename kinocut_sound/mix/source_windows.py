"""Select source PCM once before timeline placement and post-roll transitions."""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.defaults import DEFAULT_MIX_CHANNEL_COUNT
from kinocut_sound.timeline import CueKind, Timeline


@dataclass(frozen=True)
class SourceWindow:
    """Historical sample fields are frame positions/counts, including stereo."""

    cue_id: str
    in_sample: int
    out_sample: int
    sample_count: int
    sample_rate_hz: int


def source_window_bounds(cue, frames, rate):
    """Apply the same source-relative floating bounds and frame rounding everywhere."""
    duration = frames / rate
    start = cue.in_point_seconds if cue.in_point_seconds is not None else 0
    end = cue.out_point_seconds if cue.out_point_seconds is not None else duration
    if start >= duration or end > duration or end <= start:
        raise mix_error("source window lies outside source duration", MIX_INPUT_INVALID)
    first, last = round(start * rate), round(end * rate)
    if first < 0 or last > frames or first >= last:
        raise mix_error("source window must select actual samples", MIX_INPUT_INVALID)
    return SourceWindow(cue.cue_id, first, last, last - first, rate)


def select_source_windows(
    timeline: Timeline,
    sources: dict[str, bytes],
    sample_rate_hz: int,
    channel_count: int = DEFAULT_MIX_CHANNEL_COUNT,
) -> tuple[dict[str, bytes], tuple[SourceWindow, ...]]:
    selected = dict(sources)
    proofs = []
    for cue in timeline.cues:
        trimmed = cue.in_point_seconds is not None or cue.out_point_seconds is not None
        if cue.kind in (CueKind.SILENCE, CueKind.CHAPTER_MARKER):
            if trimmed:
                raise mix_error("silent cues cannot select source windows", MIX_INPUT_INVALID)
            continue
        if cue.cue_id not in sources:
            raise mix_error("source window requires its cue source", MIX_INPUT_INVALID)
        samples, rate, channels = decode_pcm_wav(sources[cue.cue_id])
        if rate != sample_rate_hz or channels != channel_count:
            raise mix_error("clip sample rate or channel count mismatch", MIX_INPUT_INVALID)
        frames = len(samples) // channels
        window = source_window_bounds(cue, frames, rate)
        if trimmed:
            selected[cue.cue_id] = pcm_to_wav(
                samples[window.in_sample * channels : window.out_sample * channels],
                sample_rate_hz=rate,
                channel_count=channels,
            )
        proofs.append(window)
    return selected, tuple(proofs)
