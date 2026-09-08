"""Finite bus sends with ordered returns and read-only pre/post-fader taps."""

from array import array
import heapq

from kinocut_sound.limits import MAX_MIX_SENDS, MAX_MIX_ROUTING_BUSES, MAX_MIX_SEND_WORK_UNITS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix.pcm_ops import _scale_in_place, _overlay_scaled
from kinocut_sound.routing import Bus, SendReturn, PanLaw
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS


def _models(buses, sends):
    if not isinstance(buses, (tuple, list)) or not isinstance(sends, (tuple, list)) or not sends:
        raise mix_error("send graph requires bus and nonempty send arrays", MIX_INPUT_INVALID)
    if len(buses) > MAX_MIX_ROUTING_BUSES or len(sends) > MAX_MIX_SENDS:
        raise mix_error("send graph exceeds cardinality limits", MIX_OVER_LIMIT)
    try:
        normalized_buses = tuple(Bus.model_validate(bus.model_dump(mode="python")) for bus in buses)
        normalized_sends = []
        for send in sends:
            raw = send.model_dump(mode="python")
            if type(raw.get("post_fader")) is not bool:
                raise mix_error("send post_fader must be a boolean", MIX_INPUT_INVALID)
            normalized_sends.append(SendReturn.model_validate(raw))
    except (AttributeError, TypeError, ValueError) as exc:
        raise mix_error("invalid send graph models", MIX_INPUT_INVALID) from exc
    return normalized_buses, tuple(normalized_sends)


class BusSendGraph:
    def __init__(self, buses, sends, frame_count, channels):
        if (
            type(frame_count) is not int
            or frame_count < 1
            or type(channels) is not int
            or channels not in PCM_MIX_CHANNEL_COUNTS
        ):
            raise mix_error("send graph requires positive mono/stereo frame shape", MIX_INPUT_INVALID)
        normalized_buses, self.sends = _models(buses, sends)
        self.buses = {bus.bus_id: bus for bus in normalized_buses}
        if len(self.buses) != len(normalized_buses) or len({send.send_id for send in self.sends}) != len(self.sends):
            raise mix_error("bus and send ids must be unique", MIX_INPUT_INVALID)
        if any(bus.pan_law != PanLaw.LINEAR for bus in normalized_buses):
            raise mix_error("bus sends require linear bus pan metadata", "mix_unsupported_intent")
        if any(
            send.source_bus_id not in self.buses or send.destination_bus_id not in self.buses for send in self.sends
        ):
            raise mix_error("send endpoints must name declared buses", MIX_INPUT_INVALID)
        self.frame_count, self.channels = frame_count, channels
        self.order = self._topology()
        self.pre_sources = {send.source_bus_id for send in self.sends if not send.post_fader}
        self.incoming = {
            bus: tuple(send for send in self.sends if send.destination_bus_id == bus) for bus in self.buses
        }
        self.work_units = (
            frame_count * channels * (len(self.buses) + 2 * len(self.sends) + len(self.pre_sources))
            + len(self.buses)
            + len(self.sends)
        )
        if self.work_units > MAX_MIX_SEND_WORK_UNITS:
            raise mix_error("send graph exceeds work-unit budget", MIX_OVER_LIMIT)

    def _topology(self):
        incoming = {bus: 0 for bus in self.buses}
        outgoing = {bus: [] for bus in self.buses}
        for send in self.sends:
            incoming[send.destination_bus_id] += 1
            outgoing[send.source_bus_id].append(send.destination_bus_id)
        ready = [bus for bus, count in incoming.items() if count == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            source = heapq.heappop(ready)
            order.append(source)
            for target in outgoing[source]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    heapq.heappush(ready, target)
        if len(order) != len(self.buses):
            raise mix_error("send graph cycles require unsupported feedback or delay", "mix_unsupported_intent")
        return tuple(order)

    @property
    def snapshot_bytes(self):
        return 2 * self.frame_count * self.channels * len(self.pre_sources)

    def _validate_canvases(self, canvases):
        if not isinstance(canvases, dict) or set(canvases) != set(self.buses):
            raise mix_error("send canvases must match declared buses", MIX_INPUT_INVALID)
        expected = self.frame_count * self.channels
        if any(
            type(samples) is not array or samples.typecode != "h" or len(samples) != expected
            for samples in canvases.values()
        ):
            raise mix_error("send canvases require matching PCM16 frames", MIX_INPUT_INVALID)
        if len({id(samples) for samples in canvases.values()}) != len(canvases):
            raise mix_error("send canvases must not alias one another", MIX_INPUT_INVALID)

    def process_buses(self, canvases):
        self._validate_canvases(canvases)
        pre, post = {}, {}
        remaining = {
            source: sum(not send.post_fader and send.source_bus_id == source for send in self.sends)
            for source in self.pre_sources
        }
        for bus_id in self.order:
            target = canvases[bus_id]
            for send in self.incoming[bus_id]:
                source = post[send.source_bus_id] if send.post_fader else pre[send.source_bus_id]
                _overlay_scaled(target, source, 10 ** (send.gain_db / 20))
                if not send.post_fader:
                    remaining[send.source_bus_id] -= 1
                    if remaining[send.source_bus_id] == 0:
                        del pre[send.source_bus_id]
            if bus_id in self.pre_sources:
                pre[bus_id] = memoryview(target.tobytes()).cast("h")
            _scale_in_place(target, (10 ** (self.buses[bus_id].gain_db / 20),) * self.channels)
            post[bus_id] = memoryview(target).toreadonly()
        return canvases

    def receipt(self):
        return {
            "algorithm": "acyclic_bus_sends_v1",
            "frame_count": self.frame_count,
            "channel_count": self.channels,
            "topological_order": list(self.order),
            "pre_fader_sources": sorted(self.pre_sources),
            "incoming_order": "declaration_order",
            "source_signal": "includes_returns",
            "destination_gain": "after_returns",
            "layer_duck_detector": "before_sends_and_bus_gain",
            "sends": [
                {
                    **send.model_dump(mode="json"),
                    "order": index,
                    "gain_factor": 10 ** (send.gain_db / 20),
                    "input_tap": "post_fader" if send.post_fader else "pre_fader",
                }
                for index, send in enumerate(self.sends)
            ],
        }
