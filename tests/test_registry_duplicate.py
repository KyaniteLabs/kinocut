"""Duplicate / near-duplicate clip detection over the approved clip registry (#39)."""

from __future__ import annotations

import pytest

from kinocut.contracts.registry import ClipRecord
from kinocut.projectstore import append_record, open_project
from kinocut.registry import duplicate_clip_groups
from tests.registry_fixtures import clip_record_kwargs

_ASSET = "sha256:" + "d" * 64
_ASSET_B = "sha256:" + "e" * 64
_EMB = "sha256:" + "1" * 64
_EMB_B = "sha256:" + "2" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _clip(project, asset_id=_ASSET, embedding_ref=None, **overrides) -> ClipRecord:
    return ClipRecord(
        **clip_record_kwargs(
            project_id=project.project_id,
            asset_id=asset_id,
            embedding_ref=embedding_ref,
            **overrides,
        )
    )


def test_exact_asset_id_duplicates_group_together(project):
    # Same output bytes (asset_id), different source provenance -> distinct
    # records that are exact byte-duplicates of one another.
    append_record(project, _clip(project, asset_id=_ASSET, source_asset_id="sha256:" + "5" * 64))
    append_record(project, _clip(project, asset_id=_ASSET, source_asset_id="sha256:" + "6" * 64))
    groups = duplicate_clip_groups(project)
    assert len(groups.exact) == 1
    assert len(groups.exact[0].asset_ids) == 1
    assert groups.exact[0].clip_count == 2


def test_distinct_assets_are_not_exact_duplicates(project):
    append_record(project, _clip(project, asset_id=_ASSET))
    append_record(project, _clip(project, asset_id=_ASSET_B))
    groups = duplicate_clip_groups(project)
    assert groups.exact == ()


def test_perceptual_near_duplicates_group_by_embedding(project):
    # Two distinct asset bytes that share a perceptual embedding cluster together.
    append_record(project, _clip(project, asset_id=_ASSET, embedding_ref=_EMB))
    append_record(project, _clip(project, asset_id=_ASSET_B, embedding_ref=_EMB))
    groups = duplicate_clip_groups(project)
    assert len(groups.perceptual) == 1
    assert groups.perceptual[0].embedding_ref == _EMB
    assert groups.perceptual[0].clip_count == 2


def test_clips_without_embedding_are_not_perceptually_grouped(project):
    append_record(project, _clip(project, asset_id=_ASSET, embedding_ref=None))
    append_record(project, _clip(project, asset_id=_ASSET_B, embedding_ref=None))
    groups = duplicate_clip_groups(project)
    assert groups.perceptual == ()


def test_duplicate_groups_exclude_superseded_records(project):
    first = append_record(project, _clip(project, asset_id=_ASSET))
    append_record(
        project,
        _clip(project, asset_id=_ASSET, supersedes=first.record_id),
    )
    groups = duplicate_clip_groups(project)
    # The superseded first record is excluded; only one active clip remains.
    assert groups.exact == ()
