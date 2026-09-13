"""Compose existing track DSP with an independently bounded bus-send graph."""

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix.bus_sends import BusSendGraph
from kinocut_sound.mix.static_routing import StaticRouting, _validated_routing


class SentRouting:
    def __init__(self, routing, track_processor, frame_count, channels):
        self.routing = _validated_routing(routing)
        if not isinstance(track_processor, StaticRouting) or track_processor.channels != channels:
            raise mix_error("send routing requires a compatible track processor", MIX_INPUT_INVALID)
        expected = self.routing.model_copy(update={"sends": ()})
        expected_hash = canonical_digest(expected.model_dump(mode="json"))
        if canonical_digest(track_processor.routing.model_dump(mode="json")) != expected_hash:
            raise mix_error("send track processor differs from declared routing", MIX_INPUT_INVALID)
        self.track_processor = track_processor
        self.graph = BusSendGraph(self.routing.buses, self.routing.sends, frame_count, channels)
        self.bindings, self.tracks = track_processor.bindings, track_processor.tracks
        self.automation = getattr(track_processor, "automation", None)

    def process_sources(self, sources, sample_rate_hz):
        return self.track_processor.process_sources(sources, sample_rate_hz)

    def process_buses(self, canvases):
        return self.graph.process_buses(canvases)

    def check_work(self, source_frames):
        if self.automation is None:
            return 0
        return self.track_processor.check_work(source_frames)

    def receipt(self):
        receipt = self.track_processor.receipt()
        receipt["track_algorithm"] = receipt["algorithm"]
        receipt["algorithm"] = "sent_pcm16_ties_even_v1"
        receipt["sends"] = self.graph.receipt()
        return receipt
