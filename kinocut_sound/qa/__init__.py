"""``kinocut_sound.qa`` — QA and metadata leaf (S11)."""

from __future__ import annotations
from kinocut_sound.qa._errors import (
    QA_ARTIFACT_DETECTED,
    QA_ASR_MISMATCH,
    QA_INPUT_INVALID,
    QA_LOUDNESS_FAIL,
    QA_STEM_FAIL,
    QA_UNAVAILABLE,
    QaError,
    qa_error,
)
from kinocut_sound.qa.loudness import LoudnessReport, check_loudness, measure_loudness
from kinocut_sound.qa.asr import AsrReport, AsrSegment, FakeAsrPort, verify_script_asr
from kinocut_sound.qa.artifact import ArtifactReport, detect_artifacts
from kinocut_sound.qa.metadata import ChapterMarker, EpisodeMetadata, build_metadata
from kinocut_sound.qa.season import EpisodeQaSummary, SeasonQaReport, rollup_season

__all__ = [
    "AsrReport",
    "AsrSegment",
    "ArtifactReport",
    "ChapterMarker",
    "EpisodeMetadata",
    "EpisodeQaSummary",
    "FakeAsrPort",
    "LoudnessReport",
    "QA_ARTIFACT_DETECTED",
    "QA_ASR_MISMATCH",
    "QA_INPUT_INVALID",
    "QA_LOUDNESS_FAIL",
    "QA_STEM_FAIL",
    "QA_UNAVAILABLE",
    "QaError",
    "SeasonQaReport",
    "build_metadata",
    "check_loudness",
    "detect_artifacts",
    "measure_loudness",
    "qa_error",
    "rollup_season",
    "verify_script_asr",
]
