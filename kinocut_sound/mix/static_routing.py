"""Bounded static PCM routing; evidence and rendering use the same factors."""

from math import cos, pi, sin

from pydantic import ValidationError

from kinocut_sound.limits import MAX_MIX_ROUTING_TRACKS, MAX_MIX_ROUTING_BUSES, MAX_MIX_ROUTING_BINDINGS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.routing import Routing, PanLaw
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS
from kinocut_sound.mix.pcm_ops import _scale_in_place


def _pan_scales(track, channels):
    if channels == 1:
        if track.pan_position != 0 or track.pan_law != PanLaw.LINEAR:
            raise mix_error("mono routing supports centered linear pan only", "mix_unsupported_intent")
        return (1.0,)
    p = track.pan_position
    if track.pan_law == PanLaw.LINEAR:
        return ((1 - p) / 2, (1 + p) / 2)
    if track.pan_law == PanLaw.CONSTANT_POWER:
        angle = (p + 1) * pi / 4
        return (cos(angle), sin(angle))
    return (min(1.0, 1 - p), min(1.0, 1 + p))


class StaticRouting:
    """Compile validated track state once and apply it without per-track canvases."""

    def __init__(self, routing, cue_tracks, channels, stem_ids, cue_ids):
        try:
            self.routing = Routing.model_validate(routing.model_dump(mode="python"))
        except (AttributeError, ValidationError, TypeError, ValueError) as exc:
            raise mix_error("invalid static routing", MIX_INPUT_INVALID) from exc
        routing = self.routing
        if type(channels) is not int or channels not in PCM_MIX_CHANNEL_COUNTS:
            raise mix_error("static routing requires mono or stereo", MIX_INPUT_INVALID)
        if (
            len(routing.tracks) > MAX_MIX_ROUTING_TRACKS
            or len(routing.buses) > MAX_MIX_ROUTING_BUSES
            or len(cue_tracks) > MAX_MIX_ROUTING_BINDINGS
        ):
            raise mix_error("static routing exceeds cardinality limits", MIX_OVER_LIMIT)
        if (
            routing.sends
            or routing.sidechains
            or routing.envelopes
            or routing.latency != Routing().latency
            or any(bus.pan_law != PanLaw.LINEAR for bus in routing.buses)
        ):
            raise mix_error("only static track routing and bus gain are supported", "mix_unsupported_intent")
        self.channels = channels
        self.bindings = dict(cue_tracks)
        tracks = {track.track_id: track for track in routing.tracks}
        if len(self.bindings) != len(cue_tracks) or set(self.bindings) != set(cue_ids):
            raise mix_error("every audible cue requires exactly one track binding", MIX_INPUT_INVALID)
        if set(self.bindings.values()) != set(tracks):
            raise mix_error("track bindings must resolve and every track must be used", MIX_INPUT_INVALID)
        if {bus.bus_id for bus in routing.buses} != set(stem_ids):
            raise mix_error("routing buses must match delivery stems", MIX_INPUT_INVALID)
        solo = any(track.soloed for track in tracks.values())
        self.tracks = {}
        for name, track in tracks.items():
            scales = _pan_scales(track, channels)
            audible = not track.muted and (not solo or track.soloed)
            gain = 10 ** (track.gain_db / 20) if audible else 0.0
            self.tracks[name] = (track, tuple(gain * scale for scale in scales), audible)

    def process_sources(self, sources, sample_rate_hz):
        if set(sources) != set(self.bindings):
            raise mix_error("routing source bindings mismatch", MIX_INPUT_INVALID)
        result = {}
        for cue_id, data in sources.items():
            samples, rate, channels = decode_pcm_wav(data)
            if channels != self.channels or rate != sample_rate_hz:
                raise mix_error("routed source format mismatch", MIX_INPUT_INVALID)
            _scale_in_place(samples, self.tracks[self.bindings[cue_id]][1])
            result[cue_id] = pcm_to_wav(samples, sample_rate_hz=rate, channel_count=channels)
        return result

    def apply_bus_gains(self, canvases):
        if set(canvases) != {bus.bus_id for bus in self.routing.buses}:
            raise mix_error("routing stem buffers mismatch", MIX_INPUT_INVALID)
        for bus in self.routing.buses:
            _scale_in_place(canvases[bus.bus_id], (10 ** (bus.gain_db / 20),) * self.channels)

    def receipt(self):
        return {
            "algorithm": "static_pcm16_ties_even_v1",
            "cue_tracks": [{"cue_id": cue, "track_id": track} for cue, track in sorted(self.bindings.items())],
            "tracks": [
                {**track.model_dump(mode="json"), "audible": audible, "channel_factors": list(factors)}
                for _, (track, factors, audible) in sorted(self.tracks.items())
            ],
            "buses": [
                {"bus_id": bus.bus_id, "gain_db": bus.gain_db}
                for bus in sorted(self.routing.buses, key=lambda bus: bus.bus_id)
            ],
        }
