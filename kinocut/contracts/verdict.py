"""``ClipVerdict`` and its closed ``Disposition`` set (design §4.4).

A verdict binds the exact asset hash and an editorial disposition. Only
``approved_with_trim`` may carry a range, and it must be non-empty and bounded.
Approved-only search uses a positive list: only ``approved`` and
``approved_with_trim`` may enter it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from kinocut.contracts._common import AssetId, RecordBase, Sha256


class Disposition(StrEnum):
    """The only editorial dispositions a clip verdict may carry."""

    APPROVED = "approved"
    APPROVED_WITH_TRIM = "approved_with_trim"
    BACKGROUND_ONLY = "background_only"
    REPAIRABLE = "repairable"
    STILL_FRAME_SALVAGE = "still_frame_salvage"
    REJECTED = "rejected"
    REGENERATE = "regenerate"


# Approved-only search is a positive list. Every salvage/intermediate state is
# excluded unless a later human verdict explicitly approves it.
_APPROVED = frozenset({Disposition.APPROVED, Disposition.APPROVED_WITH_TRIM})


class ClipVerdict(RecordBase):
    """Editorial analysis or approval bound to an exact asset hash (design §4.4)."""

    record_kind: Literal["clip_verdict"] = "clip_verdict"

    asset_hash: AssetId
    disposition: Disposition
    approved_range: tuple[float, float] | None = None
    # Bound to the exact acceptance record by its canonical id, never a label.
    acceptance_spec_id: Sha256
    reviewer: str
    rationale: str
    defect_ids: tuple[Sha256, ...] = ()
    review_decision_id: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_range_for_disposition(self) -> ClipVerdict:
        """Only ``approved_with_trim`` may carry a range, and it must be bounded.

        Every other disposition must leave ``approved_range`` unset — a stray
        range on e.g. a ``rejected`` verdict would be a silent contradiction.
        """

        if self.disposition is Disposition.APPROVED_WITH_TRIM:
            if self.approved_range is None:
                raise ValueError("approved_with_trim requires an approved_range")
            start, end = self.approved_range
            if start < 0.0 or end <= start:
                raise ValueError("approved_range must be a non-empty, non-negative range")
        elif self.approved_range is not None:
            raise ValueError(f"{self.disposition.value!r} must not carry an approved_range")
        return self

    def enters_approved_search(self) -> bool:
        """Whether this verdict may appear in an approved-only search result."""

        return self.disposition in _APPROVED
