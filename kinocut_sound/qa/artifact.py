"""Simple artifact detection for clicks/glitches."""

from __future__ import annotations
from dataclasses import dataclass
from kinocut_sound.mix._wav import parse_wav
from kinocut_sound.qa._errors import QA_ARTIFACT_DETECTED, qa_error


@dataclass(frozen=True)
class ArtifactReport:
    click_count: int
    max_jump: int
    ok: bool


def detect_artifacts(wav_bytes: bytes, *, jump_threshold: int = 20000) -> ArtifactReport:
    samples, _ = parse_wav(wav_bytes)
    clicks = 0
    max_jump = 0
    for i in range(1, len(samples)):
        jump = abs(samples[i] - samples[i - 1])
        max_jump = max(max_jump, jump)
        if jump >= jump_threshold:
            clicks += 1
    ok = clicks == 0
    report = ArtifactReport(click_count=clicks, max_jump=max_jump, ok=ok)
    if not ok:
        raise qa_error("artifact clicks detected", QA_ARTIFACT_DETECTED)
    return report
