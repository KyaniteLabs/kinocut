"""Bounded global-frame automation curves with per-clip forward cursors."""

from bisect import bisect_right
from dataclasses import dataclass
from math import isfinite

from kinocut_sound.limits import (
    MAX_MIX_AUTOMATION_ENVELOPES,
    MAX_MIX_AUTOMATION_POINTS_PER_ENVELOPE,
    MAX_MIX_AUTOMATION_POINTS,
    MIN_GAIN_DB,
    MAX_GAIN_DB,
    MIN_PAN_POSITION,
    MAX_PAN_POSITION,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS


@dataclass(frozen=True)
class _Curve:
    frames: tuple[int, ...]
    values: tuple[float, ...]
    times: tuple[float, ...]

    def cursor(self, start_frame):
        return _Cursor(self, max(0, bisect_right(self.frames, start_frame) - 1))


class _Cursor:
    def __init__(self, curve, index):
        self.curve, self.index = curve, index

    def value(self, frame):
        frames, values = self.curve.frames, self.curve.values
        if frame <= frames[0]:
            return values[0]
        while self.index + 1 < len(frames) and frame >= frames[self.index + 1]:
            self.index += 1
        index = self.index
        if index == len(frames) - 1 or frame == frames[index]:
            return values[index]
        fraction = (frame - frames[index]) / (frames[index + 1] - frames[index])
        return values[index] + (values[index + 1] - values[index]) * fraction


def _compile_curve(envelope, rate, output_frames, channels):
    bounds = {"gain_db": (MIN_GAIN_DB, MAX_GAIN_DB), "pan_position": (MIN_PAN_POSITION, MAX_PAN_POSITION)}
    if envelope.parameter not in bounds:
        raise mix_error("automation supports gain_db and pan_position only", "mix_unsupported_intent")
    low, high = bounds[envelope.parameter]
    frames, values, times = [], [], []
    for point in envelope.points:
        scaled = point.time_seconds * rate
        if not isfinite(scaled) or not isfinite(point.value) or not low <= point.value <= high:
            raise mix_error("automation point exceeds parameter bounds", MIX_INPUT_INVALID)
        frame = round(scaled)
        if not 0 <= frame <= output_frames or (frames and frame <= frames[-1]):
            raise mix_error("automation frames must be distinct and within the timeline", MIX_INPUT_INVALID)
        if channels == 1 and envelope.parameter == "pan_position" and point.value != 0:
            raise mix_error("mono automation supports centered pan only", "mix_unsupported_intent")
        frames.append(frame)
        values.append(point.value)
        times.append(point.time_seconds)
    return _Curve(tuple(frames), tuple(values), tuple(times))


class CompiledAutomation:
    def __init__(self, envelopes, rate, output_frames, channels):
        if type(rate) is not int or rate < 1 or type(channels) is not int or channels not in PCM_MIX_CHANNEL_COUNTS:
            raise mix_error("automation requires a positive rate and mono/stereo frames", MIX_INPUT_INVALID)
        if not isinstance(envelopes, (tuple, list)) or not envelopes:
            raise mix_error("automation requires nonempty envelopes", MIX_INPUT_INVALID)
        if type(output_frames) is not int or output_frames < 1:
            raise mix_error("automation requires a positive output frame count", MIX_INPUT_INVALID)
        if len(envelopes) > MAX_MIX_AUTOMATION_ENVELOPES:
            raise mix_error("automation envelope count exceeds limit", MIX_OVER_LIMIT)
        self.by_track = {}
        self.point_count = 0
        self.envelope_count = len(envelopes)
        for envelope in envelopes:
            if not envelope.points:
                raise mix_error("automation requires points", MIX_INPUT_INVALID)
            self.point_count += len(envelope.points)
            if (
                len(envelope.points) > MAX_MIX_AUTOMATION_POINTS_PER_ENVELOPE
                or self.point_count > MAX_MIX_AUTOMATION_POINTS
            ):
                raise mix_error("automation point count exceeds limit", MIX_OVER_LIMIT)
            track = self.by_track.setdefault(envelope.target_track_id, {})
            if envelope.parameter in track:
                raise mix_error("duplicate track automation parameter", MIX_INPUT_INVALID)
            track[envelope.parameter] = _compile_curve(envelope, rate, output_frames, channels)

    def work_units(self, source_frames, bindings, channels):
        expected = {cue for cue, track in bindings.items() if track in self.by_track}
        if set(source_frames) != expected:
            raise mix_error("automated source frame identities mismatch", MIX_INPUT_INVALID)
        work = self.point_count + self.envelope_count
        for cue, frames in source_frames.items():
            if type(frames) is not int or frames < 1:
                raise mix_error("automation requires positive source frames", MIX_INPUT_INVALID)
            curves = self.by_track[bindings[cue]].values()
            work += frames * channels * (1 + len(curves))
            work += sum(len(curve.frames) + len(curve.frames).bit_length() + 1 for curve in curves)
        return work

    def receipt(self):
        return {
            "algorithm": "global_linear_parameters_v1",
            "time_scope": "global_output_frames",
            "interpolation": "linear_parameter",
            "endpoint_policy": "hold_first_last",
            "rounding": "ties_to_even",
            "envelopes": [
                {
                    "target_track_id": track,
                    "parameter": parameter,
                    "points": [
                        {"time_seconds": time, "frame": frame, "value": value}
                        for time, frame, value in zip(curve.times, curve.frames, curve.values, strict=True)
                    ],
                }
                for track, curves in sorted(self.by_track.items())
                for parameter, curve in sorted(curves.items())
            ],
        }
