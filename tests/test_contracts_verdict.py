"""Tests for ``ClipVerdict`` and ``Disposition`` (design §4.4).

The dispositions are a closed editorial set. ``approved_with_trim`` requires a
non-empty bounded range; approved-only search admits only the two explicit
approved dispositions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.verdict import ClipVerdict, Disposition
from tests.contracts_fixtures import verdict_kwargs


def test_clip_verdict_dispositions_are_closed():
    assert {d.value for d in Disposition} == {
        "approved",
        "approved_with_trim",
        "background_only",
        "repairable",
        "still_frame_salvage",
        "rejected",
        "regenerate",
    }


def test_clip_verdict_is_a_record():
    verdict = ClipVerdict(**verdict_kwargs())
    assert isinstance(verdict, RecordBase)
    assert canonical_record_id(verdict).startswith("sha256:")


def test_approved_with_trim_requires_bounded_range():
    with pytest.raises(ValidationError):
        ClipVerdict(**verdict_kwargs(disposition="approved_with_trim", approved_range=None))


def test_approved_with_trim_rejects_empty_or_inverted_range():
    for bad in ((1.0, 1.0), (2.0, 1.0), (-1.0, 2.0)):
        with pytest.raises(ValidationError):
            ClipVerdict(**verdict_kwargs(disposition="approved_with_trim", approved_range=bad))


def test_approved_with_trim_accepts_valid_range():
    verdict = ClipVerdict(**verdict_kwargs(disposition="approved_with_trim", approved_range=(0.5, 2.5)))
    assert verdict.approved_range == (0.5, 2.5)


def test_asset_hash_must_be_sha256_shaped():
    with pytest.raises(ValidationError):
        ClipVerdict(**verdict_kwargs(asset_hash="not-a-hash"))


def test_rejected_and_regenerate_are_not_approved_candidates():
    for disposition in ("rejected", "regenerate"):
        verdict = ClipVerdict(**verdict_kwargs(disposition=disposition))
        assert verdict.enters_approved_search() is False
    approved = ClipVerdict(**verdict_kwargs(disposition="approved"))
    assert approved.enters_approved_search() is True


@pytest.mark.parametrize(
    "disposition",
    ["background_only", "repairable", "still_frame_salvage", "rejected", "regenerate"],
)
def test_only_explicit_approved_dispositions_enter_approved_search(disposition):
    verdict = ClipVerdict(**verdict_kwargs(disposition=disposition))
    assert verdict.enters_approved_search() is False


def test_clip_verdict_is_frozen():
    verdict = ClipVerdict(**verdict_kwargs())
    with pytest.raises(ValidationError):
        verdict.reviewer = "someone-else"
