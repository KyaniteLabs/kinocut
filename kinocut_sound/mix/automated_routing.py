"""Apply absolute track parameter envelopes before placement and crossfades."""

from kinocut_sound.limits import MAX_MIX_AUTOMATION_WORK_UNITS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.mix.automation import CompiledAutomation
from kinocut_sound.mix.pcm_ops import _scale_in_place, _scale_sample
from kinocut_sound.mix.static_routing import StaticRouting, _validated_routing, _pan_scales_at


class AutomatedRouting(StaticRouting):
    def __init__(self, routing, cue_tracks, channels, stem_ids, cue_ids, *, sample_rate_hz, output_frames, cue_starts):
        checked = _validated_routing(routing)
        super().__init__(checked.model_copy(update={"envelopes": ()}), cue_tracks, channels, stem_ids, cue_ids)
        self.routing = checked
        self.sample_rate_hz = sample_rate_hz
        self.automation = CompiledAutomation(checked.envelopes, sample_rate_hz, output_frames, channels)
        self.cue_starts = dict(cue_starts)
        if set(self.cue_starts) != set(self.bindings) or any(
            type(frame) is not int or frame < 0 for frame in self.cue_starts.values()
        ):
            raise mix_error("automation requires every cue's global start frame", MIX_INPUT_INVALID)

    def check_work(self, source_frames):
        work = self.automation.work_units(source_frames, self.bindings, self.channels)
        if work > MAX_MIX_AUTOMATION_WORK_UNITS:
            raise mix_error("automation exceeds structural work budget", MIX_OVER_LIMIT)
        return work

    def _decode(self, data, rate):
        samples, actual_rate, channels = decode_pcm_wav(data)
        if rate != self.sample_rate_hz or actual_rate != rate or channels != self.channels:
            raise mix_error("automated source format mismatch", MIX_INPUT_INVALID)
        return samples

    def process_sources(self, sources, sample_rate_hz):
        if set(sources) != set(self.bindings):
            raise mix_error("automation source bindings mismatch", MIX_INPUT_INVALID)
        frames = {}
        for cue, data in sources.items():
            samples = self._decode(data, sample_rate_hz)
            if self.bindings[cue] in self.automation.by_track:
                frames[cue] = len(samples) // self.channels
            del samples
        self.check_work(frames)
        result = {}
        for cue, data in sources.items():
            samples = self._decode(data, sample_rate_hz)
            self._process(cue, samples)
            result[cue] = pcm_to_wav(samples, sample_rate_hz=sample_rate_hz, channel_count=self.channels)
        return result

    def _process(self, cue, samples):
        track_id = self.bindings[cue]
        track, factors, audible = self.tracks[track_id]
        curves = self.automation.by_track.get(track_id)
        if not curves or not audible:
            _scale_in_place(samples, factors)
            return
        start = self.cue_starts[cue]
        gain_curve = curves["gain_db"].cursor(start) if "gain_db" in curves else None
        pan_curve = curves["pan_position"].cursor(start) if "pan_position" in curves else None
        for frame in range(len(samples) // self.channels):
            gain_db = gain_curve.value(start + frame) if gain_curve else track.gain_db
            pan = pan_curve.value(start + frame) if pan_curve else track.pan_position
            gain = 10 ** (gain_db / 20)
            scales = _pan_scales_at(pan, track.pan_law, self.channels)
            for channel in range(self.channels):
                index = frame * self.channels + channel
                samples[index] = _scale_sample(samples[index], gain * scales[channel])

    def receipt(self):
        receipt = super().receipt()
        receipt["algorithm"] = "automated_pcm16_ties_even_v1"
        receipt["automation"] = self.automation.receipt()
        for binding in receipt["cue_tracks"]:
            binding["start_frame"] = self.cue_starts[binding["cue_id"]]
        for track in receipt["tracks"]:
            curves = self.automation.by_track.get(track["track_id"])
            if curves:
                del track["channel_factors"]
                track["parameter_sources"] = {
                    parameter: "envelope" if parameter in curves else "track"
                    for parameter in ("gain_db", "pan_position")
                }
        return receipt
