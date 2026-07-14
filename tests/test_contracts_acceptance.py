"""Tests for ``GenerationAcceptanceSpec`` (design §4.2).

Exact target text is stored privately: the record binds a hash and declared
region, never the raw text. Unknown fields fail on write; the record is frozen.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from tests.contracts_fixtures import acceptance_spec_kwargs


def test_acceptance_spec_is_a_record():
    spec = GenerationAcceptanceSpec(**acceptance_spec_kwargs())
    assert isinstance(spec, RecordBase)
    assert canonical_record_id(spec).startswith("sha256:")


def test_acceptance_spec_stores_exact_text_privately_not_raw():
    # Privacy: the model must hold a text hash, never the raw exact text.
    fields = GenerationAcceptanceSpec.model_fields
    assert "exact_text" not in fields
    assert "exact_text_hash" in fields
    assert "declared_text_region" in fields


def test_acceptance_spec_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(**acceptance_spec_kwargs(surprise=True))


def test_acceptance_spec_is_frozen():
    spec = GenerationAcceptanceSpec(**acceptance_spec_kwargs())
    with pytest.raises(ValidationError):
        spec.title = "mutated"


def test_acceptance_spec_requires_core_semantic_fields():
    with pytest.raises(ValidationError):
        kwargs = acceptance_spec_kwargs()
        del kwargs["spec_id"]
        GenerationAcceptanceSpec(**kwargs)


def test_acceptance_spec_exact_text_hash_must_be_sha256():
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(**acceptance_spec_kwargs(exact_text_hash="not-a-hash"))


def test_acceptance_spec_declared_region_must_be_normalized():
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(
            **acceptance_spec_kwargs(declared_text_region={"x": 1.5, "y": 0.1, "width": 0.2, "height": 0.1})
        )
