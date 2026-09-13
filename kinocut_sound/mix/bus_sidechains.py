"""Final bus ducking from fixed post-send, post-fader detector snapshots."""

from kinocut_sound.limits import MAX_MIX_SIDECHAINS, MAX_MIX_SIDECHAIN_WORK_UNITS, MAX_MIX_ROUTING_BUSES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix.bus_buffers import validate_bus_canvases, readonly_pcm_snapshot
from kinocut_sound.mix.layer_ducking import duck_pcm_in_place, ducking_parameters
from kinocut_sound.routing import DuckingSidechain
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS


def sidechain_parameters(policy, rate):
    result = ducking_parameters(policy, rate)
    result.update(
        algorithm="linked_bus_sidechains_v1",
        source_position="after_sends_and_bus_gain_before_sidechains",
        target_scope="complete_bus_stem",
    )
    return result


class BusSidechains:
    def __init__(self, policies, bus_ids, frame_count, channels, sample_rate_hz):
        if not isinstance(bus_ids, (list, tuple)) or not bus_ids or len(bus_ids) > MAX_MIX_ROUTING_BUSES:
            raise mix_error("sidechains require a bounded bus list", MIX_INPUT_INVALID)
        if any(type(bus_id) is not str for bus_id in bus_ids) or len(set(bus_ids)) != len(bus_ids):
            raise mix_error("sidechain bus ids must be unique strings", MIX_INPUT_INVALID)
        if (
            type(frame_count) is not int
            or frame_count < 1
            or type(channels) is not int
            or channels not in PCM_MIX_CHANNEL_COUNTS
        ):
            raise mix_error("sidechains require positive mono/stereo frame shape", MIX_INPUT_INVALID)
        if not isinstance(policies, (tuple, list)) or not policies:
            raise mix_error("sidechains require nonempty controller arrays", MIX_INPUT_INVALID)
        if len(policies) > MAX_MIX_SIDECHAINS:
            raise mix_error("sidechain count exceeds limit", MIX_OVER_LIMIT)
        try:
            self.policies = tuple(
                DuckingSidechain.model_validate(policy.model_dump(mode="python")) for policy in policies
            )
        except (AttributeError, ValueError, TypeError) as exc:
            raise mix_error("invalid sidechain models", MIX_INPUT_INVALID) from exc
        self.bus_ids = tuple(bus_ids)
        pairs = {(policy.source_bus_id, policy.target_bus_id) for policy in self.policies}
        if len(pairs) != len(self.policies):
            raise mix_error("sidechain source-target pairs must be unique", MIX_INPUT_INVALID)
        if any(source not in self.bus_ids or target not in self.bus_ids for source, target in pairs):
            raise mix_error("sidechain endpoints must be declared buses", MIX_INPUT_INVALID)
        self.frame_count, self.channels, self.sample_rate_hz = frame_count, channels, sample_rate_hz
        self.parameters = tuple(sidechain_parameters(policy, sample_rate_hz) for policy in self.policies)
        self.sources = tuple(sorted({source for source, _ in pairs}))
        count, sources = len(self.policies), len(self.sources)
        self.work_units = frame_count * channels * (2 * count + sources) + count + sources
        if self.work_units > MAX_MIX_SIDECHAIN_WORK_UNITS:
            raise mix_error("sidechains exceed work-unit budget", MIX_OVER_LIMIT)
        self.measurements = ()

    @property
    def snapshot_bytes(self):
        return 2 * self.frame_count * self.channels * len(self.sources)

    def process_buses(self, canvases):
        validate_bus_canvases(canvases, self.bus_ids, self.frame_count, self.channels)
        snapshots = {source: readonly_pcm_snapshot(canvases[source]) for source in self.sources}
        measurements = []
        for policy in self.policies:
            summary = duck_pcm_in_place(
                canvases[policy.target_bus_id],
                snapshots[policy.source_bus_id],
                self.channels,
                self.sample_rate_hz,
                policy,
            )
            measurements.append(
                {"source_bus_id": policy.source_bus_id, "target_bus_id": policy.target_bus_id, "summary": summary}
            )
        self.measurements = tuple(measurements)
        return canvases

    def receipt(self):
        return {
            "algorithm": "linked_bus_sidechains_v1",
            "frame_count": self.frame_count,
            "channel_count": self.channels,
            "snapshot_sources": list(self.sources),
            "controller_order": "declaration_order",
            "detectors": "fixed_before_any_sidechain",
            "controllers": list(self.parameters),
        }
