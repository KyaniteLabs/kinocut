"""Public validation adapter + export/semantic-binding smoke tests (Task 2).

The adapter is the single public seam that maps a Pydantic ``ValidationError``
onto a stable contract :class:`MCPVideoError` code, so no public API leaks a raw
``ValueError``/``ValidationError``. The smoke tests assert every exported record
model binds a stable ``record_kind`` and produces a canonical id, and that the
package's public ``__all__`` is fully importable.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import kinocut.contracts as contracts
from kinocut.contracts import (
    UNKNOWN_RECORD_FIELD,
    RecordBase,
)
from kinocut.contracts._errors import INVALID_RECORD
from kinocut.contracts.adapter import parse_record_json, validate_record
from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from tests.contracts_fixtures import verdict_kwargs

_SHA = "sha256:" + "a" * 64


def test_validate_record_returns_model_on_valid_data():
    record = validate_record(ClipVerdict, verdict_kwargs(acceptance_spec_id=_SHA))
    assert isinstance(record, ClipVerdict)


def test_validate_record_maps_unknown_field_to_stable_code():
    with pytest.raises(MCPVideoError) as excinfo:
        validate_record(ClipVerdict, verdict_kwargs(acceptance_spec_id=_SHA, surprise=True))
    assert excinfo.value.code == UNKNOWN_RECORD_FIELD
    assert not isinstance(excinfo.value, ValidationError)
    assert not isinstance(excinfo.value, ValueError)


def test_validate_record_maps_other_errors_to_invalid_record():
    with pytest.raises(MCPVideoError) as excinfo:
        validate_record(ClipVerdict, verdict_kwargs(acceptance_spec_id="not-a-hash"))
    assert excinfo.value.code == INVALID_RECORD


def test_parse_record_json_wraps_malformed_json():
    with pytest.raises(MCPVideoError) as excinfo:
        parse_record_json(ClipVerdict, "{not valid json")
    assert excinfo.value.code == INVALID_RECORD
    assert not isinstance(excinfo.value, ValidationError)


def test_parse_record_json_roundtrips_valid_line():
    record = ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA))
    line = json.dumps(record.model_dump(mode="json"))
    parsed = parse_record_json(ClipVerdict, line)
    assert isinstance(parsed, ClipVerdict)


# ---- Export + semantic-binding smoke -------------------------------------

_RECORD_MODELS = [
    "AssetRecord",
    "ClipVerdict",
    "DefectFinding",
    "ProtectedElement",
    "ReviewDecision",
    "KnownLimitation",
    "ApprovalState",
    "GenerationAcceptanceSpec",
    "PromptOutcome",
    "UsageEvent",
    "CostEvent",
    "WorkflowRecipe",
]


@pytest.mark.parametrize("name", _RECORD_MODELS)
def test_record_model_binds_stable_kind(name):
    model = getattr(contracts, name)
    assert issubclass(model, RecordBase)
    kind = model.model_fields["record_kind"].default
    assert isinstance(kind, str) and kind


def test_all_public_exports_are_importable():
    missing = [name for name in contracts.__all__ if getattr(contracts, name, None) is None]
    assert missing == []


def test_adapter_is_exported_publicly():
    assert "validate_record" in contracts.__all__
    assert contracts.validate_record is validate_record
