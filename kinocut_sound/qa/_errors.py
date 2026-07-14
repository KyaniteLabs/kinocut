"""QA leaf error codes."""

from __future__ import annotations
from kinocut_sound._errors import SoundContractError

QA_INPUT_INVALID = "qa_input_invalid"
QA_LOUDNESS_FAIL = "qa_loudness_fail"
QA_ARTIFACT_DETECTED = "qa_artifact_detected"
QA_ASR_MISMATCH = "qa_asr_mismatch"
QA_STEM_FAIL = "qa_stem_fail"
QA_UNAVAILABLE = "qa_unavailable"


class QaError(SoundContractError):
    """Bounded QA failure."""


def qa_error(message: str, code: str) -> QaError:
    return QaError(message, code=code)
