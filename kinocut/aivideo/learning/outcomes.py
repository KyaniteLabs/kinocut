"""Prompt-outcome memory: privacy-safe writer and asset-linked query (#40).

A :class:`~kinocut.contracts.learning.PromptOutcome` links a generation prompt
(stored only by ``sha256`` hash — never raw text) to the assets, verdicts, and
defects it produced. Outcomes are append-only and idempotent by canonical
digest: recording the same outcome twice persists exactly one row.
"""

from __future__ import annotations

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts._errors import contract_error, INVALID_RECORD
from kinocut.contracts.learning import PromptOutcome
from kinocut.projectstore import Project, append_record, read_records


def _active_prompt_outcomes(project: Project) -> list[PromptOutcome]:
    """Return exact-type, non-superseded prompt-outcome records."""

    rows = [item for item in read_records(project, "prompt_outcome") if type(item) is PromptOutcome]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def _require_outcome_link(outcome: PromptOutcome) -> None:
    """A prompt outcome must link to at least one asset, verdict, or defect."""

    if not (outcome.asset_ids or outcome.verdict_ids or outcome.defect_ids):
        raise contract_error(
            "a prompt outcome requires at least one asset, verdict, or defect outcome link",
            INVALID_RECORD,
        )


def record_prompt_outcome(project: Project, outcome: PromptOutcome) -> PromptOutcome:
    """Persist one prompt-outcome record, idempotent by canonical digest."""

    _require_outcome_link(outcome)
    digest = canonical_record_id(outcome)
    for existing in _active_prompt_outcomes(project):
        if existing.record_id == digest:
            return existing
    appended = append_record(project, outcome)
    return appended  # type: ignore[return-value]


def prompt_outcomes_for_asset(project: Project, asset_id: str) -> list[PromptOutcome]:
    """Return active prompt outcomes that reference ``asset_id``."""

    return [item for item in _active_prompt_outcomes(project) if asset_id in item.asset_ids]


__all__ = ["prompt_outcomes_for_asset", "record_prompt_outcome"]
