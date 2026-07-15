"""Versioned AI-video acceptance benchmark (#61, design §4.12).

A deterministic, reproducible acceptance benchmark: a versioned corpus of
AI-video capabilities, run against the current toolchain to produce a
:class:`BenchmarkReceipt` that records the kinocut/FFmpeg versions and each
corpus item's availability. Comparable across toolchains and FFmpeg versions;
never a release artifact.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from kinocut.capability_report import capability_report
from kinocut.contracts._common import ValueObject

_CORPUS_VERSION = "ai-video-v1"


class BenchmarkItem(ValueObject):
    """One entry in the versioned AI-video benchmark corpus."""

    item_id: str
    capability_id: str
    description: str


class BenchmarkCorpus(ValueObject):
    """A versioned, ordered set of benchmark items."""

    corpus_version: str
    items: tuple[BenchmarkItem, ...]


class BenchmarkItemResult(ValueObject):
    """One corpus item's outcome on the current toolchain."""

    item_id: str
    capability_id: str
    availability: str  # available | unavailable | degraded


class BenchmarkReceipt(ValueObject):
    """A reproducible benchmark result manifest (#61)."""

    corpus_version: str
    kinocut_version: str | None = None
    ffmpeg_version: str | None = None
    results: tuple[BenchmarkItemResult, ...] = ()
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


AIVIDEO_CORPUS = BenchmarkCorpus(
    corpus_version=_CORPUS_VERSION,
    items=(
        BenchmarkItem(item_id="edit_mp4", capability_id="video_edit", description="Edit and export an MP4"),
        BenchmarkItem(item_id="burn_subtitles", capability_id="subtitles", description="Burn SRT VTT ASS subtitles"),
        BenchmarkItem(item_id="audio_bed", capability_id="audio", description="Compose a governed audio bed"),
        BenchmarkItem(item_id="transcribe", capability_id="ai_transcribe", description="ASR transcription to SRT"),
        BenchmarkItem(item_id="c2pa_sign", capability_id="c2pa_signing", description="Optional C2PA provenance signing"),
    ),
)


def _kinocut_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("kinocut")
    except Exception:  # pragma: no cover - defensive
        return None


def _ffmpeg_version(diagnostics: dict[str, Any]) -> str | None:
    for check in diagnostics.get("checks", []):
        if check.get("name") == "ffmpeg":
            return check.get("version")
    return None


def run_aivideo_benchmark(diagnostics: dict[str, Any] | None = None) -> BenchmarkReceipt:
    """Run the versioned AI-video corpus against the current toolchain (#61)."""

    reports = {report.capability_id: report for report in capability_report(diagnostics)}
    results: list[BenchmarkItemResult] = []
    passed = 0
    for item in AIVIDEO_CORPUS.items:
        report = reports.get(item.capability_id)
        availability = report.availability.value if report is not None else "unavailable"
        if availability == "available":
            passed += 1
        results.append(
            BenchmarkItemResult(
                item_id=item.item_id,
                capability_id=item.capability_id,
                availability=availability,
            )
        )
    diag = diagnostics if diagnostics is not None else {}
    return BenchmarkReceipt(
        corpus_version=AIVIDEO_CORPUS.corpus_version,
        kinocut_version=_kinocut_version(),
        ffmpeg_version=_ffmpeg_version(diag),
        results=tuple(results),
        passed_count=passed,
        failed_count=len(results) - passed,
    )


__all__ = [
    "AIVIDEO_CORPUS",
    "BenchmarkCorpus",
    "BenchmarkItem",
    "BenchmarkItemResult",
    "BenchmarkReceipt",
    "run_aivideo_benchmark",
]
