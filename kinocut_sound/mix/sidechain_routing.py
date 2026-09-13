"""Outer final-bus sidechain stage over existing track and send processors."""

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix.static_routing import _validated_routing, StaticRouting
from kinocut_sound.mix.sent_routing import SentRouting
from kinocut_sound.mix.bus_buffers import validate_bus_canvases
from kinocut_sound.mix.bus_sidechains import BusSidechains


class SidechainRouting:
    def __init__(self, routing, inner, frame_count, channels, rate):
        self.routing = _validated_routing(routing)
        if not isinstance(inner, (StaticRouting, SentRouting)):
            raise mix_error("sidechains require a compatible inner processor", MIX_INPUT_INVALID)
        expected = self.routing.model_copy(update={"sidechains": ()})
        if canonical_digest(expected.model_dump(mode="json")) != canonical_digest(
            inner.routing.model_dump(mode="json")
        ):
            raise mix_error("sidechain inner processor differs from declared routing", MIX_INPUT_INVALID)
        self.inner = inner
        self.sidechain_processor = BusSidechains(
            self.routing.sidechains, tuple(bus.bus_id for bus in self.routing.buses), frame_count, channels, rate
        )
        self.bindings, self.tracks = inner.bindings, inner.tracks
        self.automation = getattr(inner, "automation", None)
        self.graph = getattr(inner, "graph", None)

    @property
    def sidechain_measurements(self):
        return self.sidechain_processor.measurements

    def process_sources(self, sources, sample_rate_hz):
        return self.inner.process_sources(sources, sample_rate_hz)

    def process_buses(self, canvases):
        stage = self.sidechain_processor
        validate_bus_canvases(canvases, stage.bus_ids, stage.frame_count, stage.channels)
        return self.sidechain_processor.process_buses(self.inner.process_buses(canvases))

    def check_work(self, source_frames):
        return self.inner.check_work(source_frames) if self.automation is not None else 0

    def receipt(self):
        result = self.inner.receipt()
        result["inner_routing_algorithm"] = result["algorithm"]
        result["algorithm"] = "sidechain_pcm16_ties_even_v1"
        result["sidechains"] = self.sidechain_processor.receipt()
        return result
