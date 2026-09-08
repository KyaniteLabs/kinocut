"""Linked ambient-layer envelopes with exact frame endpoints and recovery evidence."""

from math import ceil

from kinocut_sound.defaults import DEFAULT_MIX_DUCK_THRESHOLD
from kinocut_sound.mix._errors import MIX_DUCKING_INVALID, mix_error
from kinocut_sound.mix.pcm_ops import _scale_sample
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS
from kinocut_sound.world.layers import DuckingContract


def _checked_contract(contract):
    try:
        return DuckingContract.model_validate(contract.model_dump(mode="python"))
    except (AttributeError, ValueError, TypeError) as exc:
        raise mix_error("invalid layer ducking contract", MIX_DUCKING_INVALID) from exc


def ducking_parameters(contract, sample_rate_hz):
    if type(sample_rate_hz) is not int or sample_rate_hz < 1:
        raise mix_error("ducking requires a positive sample rate", MIX_DUCKING_INVALID)
    checked = _checked_contract(contract)
    return {
        "algorithm": "linked_layer_ducking_v1",
        "contract": checked.model_dump(mode="json"),
        "detector_threshold": DEFAULT_MIX_DUCK_THRESHOLD,
        "source_position": "after_clips_before_bus_gain",
        "target_scope": "explicit_layers_only",
        "attack_frames": max(1, ceil(checked.attack_ms * sample_rate_hz / 1000)),
        "release_frames": max(1, ceil(checked.release_ms * sample_rate_hz / 1000)),
        "recovery_frames": max(1, ceil(checked.recovery_ms * sample_rate_hz / 1000)),
    }


class _Envelope:
    def __init__(self, parameters):
        self.parameters = parameters
        self.target = 10 ** (-parameters["contract"]["attenuation_db"] / 20)
        self.gain = self.minimum = self.start = 1.0
        self.active = self.ramping = False
        self.elapsed = self.active_frames = self.runs = self.releases = self.max_release = 0

    def step(self, active):
        self.active_frames += int(active)
        if active != self.active:
            self.runs += int(active)
            self.start, self.elapsed, self.ramping = self.gain, 0, True
            self.active = active
        if self.ramping:
            self.elapsed += 1
            frames = self.parameters["attack_frames" if active else "release_frames"]
            destination = self.target if active else 1.0
            if self.elapsed >= frames:
                self.gain, self.ramping = destination, False
                if not active:
                    self.releases += 1
                    self.max_release = max(self.max_release, self.elapsed)
            else:
                self.gain = self.start + (destination - self.start) * self.elapsed / frames
                self.gain = max(self.target, min(1.0, self.gain))
        self.minimum = min(self.minimum, self.gain)
        return self.gain

    def summary(self):
        truncated = self.elapsed if self.ramping and not self.active else 0
        return {
            "active_frames": self.active_frames,
            "activity_runs": self.runs,
            "minimum_gain": self.minimum,
            "final_gain": self.gain,
            "completed_releases": self.releases,
            "max_release_frames": self.max_release,
            "truncated_release_frames": truncated,
            "truncated_recovery": bool(truncated),
            "final_detector_active": self.active,
            "recovery_status": "pass" if self.releases else "not_exercised",
        }


def duck_layer_in_place(samples, detector, channels, sample_rate_hz, contract):
    """Apply a linked envelope; samples=None measures an all-inactive stack."""
    if (
        type(channels) is not int
        or channels not in PCM_MIX_CHANNEL_COUNTS
        or len(detector) % channels
        or (samples is not None and len(samples) != len(detector))
    ):
        raise mix_error("layer detector and target require matching complete frames", MIX_DUCKING_INVALID)
    envelope = _Envelope(ducking_parameters(contract, sample_rate_hz))
    for index in range(0, len(detector), channels):
        level = max(abs(detector[index + channel]) for channel in range(channels)) / 32768.0
        gain = envelope.step(level > DEFAULT_MIX_DUCK_THRESHOLD)
        if samples is not None:
            for channel in range(channels):
                samples[index + channel] = _scale_sample(samples[index + channel], gain)
    return envelope.summary()
