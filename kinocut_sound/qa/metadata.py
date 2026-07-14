"""Distribution metadata / chapters / ISRC codes."""

from __future__ import annotations
from dataclasses import dataclass
from kinocut_sound._canonical import BoundedCode
from kinocut_sound.qa._errors import QA_INPUT_INVALID, qa_error


@dataclass(frozen=True)
class ChapterMarker:
    title: str
    start_seconds: float


@dataclass(frozen=True)
class EpisodeMetadata:
    title: str
    duration_seconds: float
    chapters: tuple[ChapterMarker, ...]
    credits: tuple[str, ...]
    isrc: str | None
    loudness_lufs: float | None


def build_metadata(
    *,
    title: str,
    duration_seconds: float,
    chapters: tuple[ChapterMarker, ...] = (),
    credits: tuple[str, ...] = (),
    isrc: str | None = None,
    loudness_lufs: float | None = None,
) -> EpisodeMetadata:
    try:
        BoundedCode(title.replace(" ", "_")[:64] if " " in title else title)
    except Exception as exc:
        # titles may have spaces; require non-empty
        if not title or not title.strip():
            raise qa_error("title required", QA_INPUT_INVALID) from exc
    if duration_seconds <= 0:
        raise qa_error("duration must be positive", QA_INPUT_INVALID)
    if isrc is not None:
        try:
            BoundedCode(isrc)
        except Exception as exc:
            raise qa_error("isrc must be bounded code", QA_INPUT_INVALID) from exc
    return EpisodeMetadata(
        title=title.strip(),
        duration_seconds=float(duration_seconds),
        chapters=chapters,
        credits=credits,
        isrc=isrc,
        loudness_lufs=loudness_lufs,
    )
