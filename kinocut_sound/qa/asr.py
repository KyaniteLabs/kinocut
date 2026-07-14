"""Fake ASR verification port (D42 stand-in until S13)."""

from __future__ import annotations
from dataclasses import dataclass
from kinocut_sound.qa._errors import QA_ASR_MISMATCH, QA_UNAVAILABLE, qa_error


@dataclass(frozen=True)
class AsrSegment:
    start_seconds: float
    end_seconds: float
    text_hash: str


@dataclass(frozen=True)
class AsrReport:
    segments: tuple[AsrSegment, ...]
    mismatch_count: int
    ok: bool


class FakeAsrPort:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def verify(self, *, script_hashes: tuple[str, ...], audio_duration_seconds: float) -> AsrReport:
        if not self.available:
            raise qa_error("ASR port unavailable", QA_UNAVAILABLE)
        segs = []
        step = audio_duration_seconds / max(1, len(script_hashes))
        for i, h in enumerate(script_hashes):
            segs.append(
                AsrSegment(start_seconds=i * step, end_seconds=min(audio_duration_seconds, (i + 1) * step), text_hash=h)
            )
        # perfect match fake
        return AsrReport(segments=tuple(segs), mismatch_count=0, ok=True)


def verify_script_asr(*, port: FakeAsrPort, script_hashes: tuple[str, ...], audio_duration_seconds: float) -> AsrReport:
    report = port.verify(script_hashes=script_hashes, audio_duration_seconds=audio_duration_seconds)
    if not report.ok:
        raise qa_error("ASR mismatch", QA_ASR_MISMATCH)
    return report
