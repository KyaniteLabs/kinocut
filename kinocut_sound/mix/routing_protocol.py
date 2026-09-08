"""Structural DSP boundary shared by static, automated and send routing."""

from array import array
from typing import Protocol


class RoutingProcessor(Protocol):
    bindings: dict[str, str]
    tracks: dict

    def process_sources(self, sources: dict[str, bytes], sample_rate_hz: int) -> dict[str, bytes]: ...

    def process_buses(self, canvases: dict[str, array]) -> dict[str, array]: ...

    def receipt(self) -> dict: ...
