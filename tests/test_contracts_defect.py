"""Tests for ``DefectFinding``, ``DefectCode``, ``DefectStatus`` (design §4.5).

The taxonomy is a stable closed set carrying a version. A finding whose status
is anything other than ``suspected`` requires a human decision reference.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.defect import (
    TAXONOMY_VERSION,
    DefectCode,
    DefectFinding,
    DefectStatus,
)
from tests.contracts_fixtures import defect_kwargs


def test_defect_code_taxonomy_is_closed_and_versioned():
    assert TAXONOMY_VERSION == 1
    assert {c.value for c in DefectCode} == {
        "text_drift",
        "identity_drift",
        "object_mutation",
        "warping",
        "flicker",
        "unwanted_camera_motion",
        "continuity_failure",
        "late_frame_degradation",
        "frozen_frames",
        "black_frames",
        "corrupt_frames",
        "broken_loop",
        "subtitle_overflow",
        "subtitle_timing",
        "audio_duration",
        "audio_style_seam",
        "voice_identity_seam",
    }


def test_defect_status_is_closed():
    assert {s.value for s in DefectStatus} == {
        "suspected",
        "confirmed",
        "accepted_limitation",
        "resolved",
        "false_positive",
    }


def test_defect_finding_is_a_record():
    finding = DefectFinding(**defect_kwargs())
    assert isinstance(finding, RecordBase)
    assert canonical_record_id(finding).startswith("sha256:")


def test_suspected_status_allows_missing_human_decision():
    finding = DefectFinding(**defect_kwargs(status="suspected", human_decision_id=None))
    assert finding.human_decision_id is None


def test_non_suspected_status_requires_human_decision():
    for status in ("confirmed", "accepted_limitation", "resolved", "false_positive"):
        with pytest.raises(ValidationError):
            DefectFinding(**defect_kwargs(status=status, human_decision_id=None))


def test_non_suspected_status_accepts_human_decision():
    finding = DefectFinding(**defect_kwargs(status="confirmed", human_decision_id="sha256:" + "d" * 64))
    assert finding.status is DefectStatus.CONFIRMED


def test_defect_time_range_must_be_ordered():
    with pytest.raises(ValidationError):
        DefectFinding(**defect_kwargs(time_range=(2.0, 1.0)))


def test_defect_finding_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        DefectFinding(**defect_kwargs(surprise=True))
