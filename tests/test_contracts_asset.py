"""Tests for ``AssetRecord`` and ``GenerationLineage`` (design §4.3).

Media identities are byte-hash asset ids. Provenance is stored by hash, never
raw prompt text. Original locations are project-relative — never home paths or
absolute paths that could leak the host filesystem.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.asset import AssetRecord, GenerationLineage, MediaKind
from tests.contracts_fixtures import (
    asset_record_kwargs,
    generation_lineage_kwargs,
)


def test_asset_record_is_a_record():
    asset = AssetRecord(**asset_record_kwargs())
    assert isinstance(asset, RecordBase)
    assert canonical_record_id(asset).startswith("sha256:")


def test_asset_id_must_be_sha256_shaped():
    with pytest.raises(ValidationError):
        AssetRecord(**asset_record_kwargs(asset_id="not-a-hash"))


def test_media_kind_is_a_closed_enum():
    assert {k.value for k in MediaKind} == {"video", "audio", "image", "subtitle"}


def test_asset_record_rejects_absolute_or_home_original_location():
    for bad in ("/Users/someone/clip.mp4", "~/clip.mp4", "/abs/path.mp4"):
        with pytest.raises(ValidationError):
            AssetRecord(**asset_record_kwargs(original_location=bad))


def test_asset_record_stores_prompt_by_hash_not_raw_text():
    # Provenance lives in GenerationLineage; it must never carry raw prompt text.
    assert "prompt" not in GenerationLineage.model_fields
    assert "prompt_hash" in GenerationLineage.model_fields


def test_generation_lineage_is_embeddable_value_object():
    lineage = GenerationLineage(**generation_lineage_kwargs())
    asset = AssetRecord(**asset_record_kwargs(lineage=lineage.model_dump()))
    assert asset.lineage is not None
    assert asset.lineage.prompt_hash == lineage.prompt_hash


def test_generation_lineage_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        GenerationLineage(**generation_lineage_kwargs(surprise=True))


def test_asset_record_is_frozen():
    asset = AssetRecord(**asset_record_kwargs())
    with pytest.raises(ValidationError):
        asset.byte_size = 999
