"""Explicit post-roll crossfades that preserve authoritative cue positions."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from math import isfinite

from kinocut_sound.mix._errors import MIX_CROSSFADE_INVALID, mix_error
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
from kinocut_sound.mix.crossfade import crossfade_pair
from kinocut_sound.mix.seam import SeamEvent
from kinocut_sound.timeline import CueKind, Timeline


@dataclass(frozen=True)
class CrossfadeTransition:
    """Allow outgoing post-roll to overlap the beginning of an incoming cue.

    Source WAVs start at their cue's first sample. The outgoing source must
    contain real post-roll beyond its nominal duration. Both cues retain their
    original start, duration and stem; the incoming source is never shifted.
    """

    outgoing_cue_id: str
    incoming_cue_id: str
    duration_seconds: float

    def __post_init__(self) -> None:
        value = self.duration_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise mix_error("transition duration must be positive and finite", MIX_CROSSFADE_INVALID)
        if (
            not isinstance(self.outgoing_cue_id, str)
            or not isinstance(self.incoming_cue_id, str)
            or not self.outgoing_cue_id
            or not self.incoming_cue_id
            or self.outgoing_cue_id == self.incoming_cue_id
        ):
            raise mix_error("transition requires two distinct cue ids", MIX_CROSSFADE_INVALID)


def apply_transitions(
    timeline: Timeline,
    sources: dict[str, bytes],
    stems: dict[str, str],
    transitions: tuple[CrossfadeTransition, ...],
    sample_rate_hz: int,
) -> tuple[dict[str, bytes], list[SeamEvent]]:
    """Return changed incoming sources and receipts for actual PCM blends."""
    if not isinstance(transitions, tuple):
        raise mix_error("transitions must be a tuple", MIX_CROSSFADE_INVALID)
    changed: dict[str, bytes] = {}
    events: list[SeamEvent] = []
    positions = {cue.cue_id: i for i, cue in enumerate(timeline.cues)}
    for transition in transitions:
        if not isinstance(transition, CrossfadeTransition):
            raise mix_error("transitions must be CrossfadeTransition instances", MIX_CROSSFADE_INVALID)
        left_id, right_id = transition.outgoing_cue_id, transition.incoming_cue_id
        left_pos, right_pos = positions.get(left_id), positions.get(right_id)
        if left_pos is None or right_pos != left_pos + 1 or right_id in changed:
            raise mix_error("transition must name unique adjacent cues", MIX_CROSSFADE_INVALID)
        left, right = timeline.cues[left_pos], timeline.cues[right_pos]
        if left.kind is not CueKind.LINE or right.kind is not CueKind.LINE:
            raise mix_error("transitions require adjacent dialogue cues", MIX_CROSSFADE_INVALID)
        if round(left.start_seconds * sample_rate_hz) + round(left.duration_seconds * sample_rate_hz) != round(
            right.start_seconds * sample_rate_hz
        ):
            raise mix_error("transitions cannot cross timeline gaps", MIX_CROSSFADE_INVALID)
        if stems.get(left_id) != stems.get(right_id) or left_id not in sources or right_id not in sources:
            raise mix_error("transition sources must exist on the same stem", MIX_CROSSFADE_INVALID)
        if transition.duration_seconds > right.duration_seconds:
            raise mix_error("transition window must fit the incoming cue", MIX_CROSSFADE_INVALID)
        fade_n = round(transition.duration_seconds * sample_rate_hz)
        window_n = round(left.duration_seconds * sample_rate_hz)
        if fade_n <= 0 or fade_n > round(right.duration_seconds * sample_rate_hz):
            raise mix_error("transition window must fit the incoming cue", MIX_CROSSFADE_INVALID)
        outgoing, left_rate = parse_wav(sources[left_id])
        incoming, right_rate = parse_wav(sources[right_id])
        if left_rate != sample_rate_hz or right_rate != sample_rate_hz:
            raise mix_error("transition source sample rate mismatch", MIX_CROSSFADE_INVALID)
        if len(outgoing) < window_n + fade_n or len(incoming) < fade_n:
            raise mix_error("transition requires real outgoing post-roll and incoming samples", MIX_CROSSFADE_INVALID)
        blended = crossfade_pair(
            pcm_to_wav(outgoing[window_n : window_n + fade_n], sample_rate_hz=sample_rate_hz),
            pcm_to_wav(incoming[:fade_n], sample_rate_hz=sample_rate_hz),
            fade_seconds=fade_n / sample_rate_hz,
        )
        updated = array("h", incoming)
        updated[:fade_n] = parse_wav(blended)[0]
        changed[right_id] = pcm_to_wav(updated, sample_rate_hz=sample_rate_hz)
        at_seconds = round(right.start_seconds * sample_rate_hz) / sample_rate_hz
        events.append(SeamEvent("crossfade", at_seconds, left_id, right_id, fade_n / sample_rate_hz))
    return changed, sorted(events, key=lambda event: event.at_seconds)
