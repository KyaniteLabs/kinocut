"""Timestamped seam reports for crossfades and joins (G20)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeamEvent:
    kind: str
    at_seconds: float
    left_cue_id: str
    right_cue_id: str
    duration_seconds: float


@dataclass(frozen=True)
class SeamReport:
    events: tuple[SeamEvent, ...]

    @property
    def count(self) -> int:
        return len(self.events)
