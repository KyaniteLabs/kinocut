"""Workflow run and step lifecycle states, with the legal moves between them.

A run receipt is rewritten after every stage (``in_progress``) and once more
when the run ends (``completed`` or ``failed``).  A step entry starts
``pending`` and ends ``completed`` or ``failed``.  A step reused on resume stays
``completed`` and carries ``skipped: true`` (receipt schema §5a).  The values
equal the strings stored in receipts, so receipt bytes do not change.

No transition table: a resume legally reopens a ``failed`` (or even a
``completed``) receipt as ``in_progress``, so the only ordering rule is the
executor's own loop (``in_progress`` after each stage, one terminal write).
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
