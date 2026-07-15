"""Prompt-outcome memory: privacy-safe writer and asset-linked query (#40)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import (
    prompt_outcomes_for_asset,
    record_prompt_outcome,
)
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.learning import PromptOutcome
from kinocut.projectstore import open_project
from tests.contracts_fixtures import prompt_outcome_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _outcome(project, **overrides) -> PromptOutcome:
    return PromptOutcome(**prompt_outcome_kwargs(project_id=project.project_id, **overrides))


def test_record_prompt_outcome_assigns_canonical_record_id(project):
    outcome = _outcome(project)
    stored = record_prompt_outcome(project, outcome)
    assert stored.record_id == canonical_record_id(outcome)
    assert stored.record_kind == "prompt_outcome"


def test_record_prompt_outcome_is_idempotent_by_digest(project):
    outcome = _outcome(project)
    first = record_prompt_outcome(project, outcome)
    second = record_prompt_outcome(project, outcome)
    assert first.record_id == second.record_id


def test_prompt_outcome_stores_prompt_hash_never_raw_text(project):
    stored = record_prompt_outcome(project, _outcome(project))
    # Only the hash is persisted; no raw prompt field exists on the record.
    assert stored.prompt_hash.startswith("sha256:")
    assert not hasattr(stored, "prompt_text")
    dumped = stored.model_dump()
    assert "prompt_text" not in dumped
    assert dumped["prompt_hash"].count(":") == 1


def test_prompt_outcome_requires_at_least_one_outcome_link(project):
    # A prompt linked to no asset, verdict, or defect carries no learning signal.
    from kinocut.errors import MCPVideoError

    bare = _outcome(project, asset_ids=(), verdict_ids=(), defect_ids=())
    with pytest.raises(MCPVideoError, match="outcome link"):
        record_prompt_outcome(project, bare)


def test_prompt_outcomes_for_asset_returns_only_active_referencing_rows(project):
    asset_a = "sha256:" + "a" * 64
    asset_b = "sha256:" + "b" * 64
    record_prompt_outcome(project, _outcome(project, asset_ids=(asset_a,)))
    record_prompt_outcome(project, _outcome(project, asset_ids=(asset_b,)))
    rows = prompt_outcomes_for_asset(project, asset_a)
    assert len(rows) == 1
    assert asset_a in rows[0].asset_ids
    assert asset_b not in rows[0].asset_ids


def test_prompt_outcomes_for_asset_excludes_superseded(project):
    asset = "sha256:" + "a" * 64
    original = record_prompt_outcome(project, _outcome(project, asset_ids=(asset,)))
    superseder = PromptOutcome(
        **prompt_outcome_kwargs(
            project_id=project.project_id,
            asset_ids=(asset,),
            supersedes=original.record_id,
            generator_model="veo-3.1",
        )
    )
    stored_superseder = record_prompt_outcome(project, superseder)
    rows = prompt_outcomes_for_asset(project, asset)
    assert len(rows) == 1
    assert rows[0].record_id == stored_superseder.record_id
