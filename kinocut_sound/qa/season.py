"""Season QA rollup."""

from __future__ import annotations
from dataclasses import dataclass
from kinocut_sound.qa.loudness import LoudnessReport
from kinocut_sound.qa.artifact import ArtifactReport


@dataclass(frozen=True)
class EpisodeQaSummary:
    episode_id: str
    loudness_ok: bool
    artifacts_ok: bool


@dataclass(frozen=True)
class SeasonQaReport:
    episode_count: int
    pass_count: int
    fail_count: int
    episodes: tuple[EpisodeQaSummary, ...]


def rollup_season(summaries: tuple[EpisodeQaSummary, ...]) -> SeasonQaReport:
    passes = sum(1 for s in summaries if s.loudness_ok and s.artifacts_ok)
    fails = len(summaries) - passes
    return SeasonQaReport(
        episode_count=len(summaries),
        pass_count=passes,
        fail_count=fails,
        episodes=summaries,
    )
