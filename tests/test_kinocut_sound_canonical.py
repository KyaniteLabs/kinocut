"""RED-first tests for the ``kinocut_sound`` canonical base and typed ids.

These witness the immutable, fail-closed record/value-object base shared by
every sound contract, plus stable canonical serialization/digestion. The rules
mirror the proven repository pattern but live entirely inside the sidecar
package so it stays usable without ``kinocut`` imported.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    RecordBase,
    canonical_digest,
    canonical_record_id,
    location_violation,
)
from kinocut_sound._errors import (
    INVALID_RECORD,
    UNKNOWN_RECORD_FIELD,
    UNSAFE_LOCATION,
    SoundContractError,
    contract_error,
)

_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64


class _FloatBearing(RecordBase):
    measure: float


class _Record(RecordBase):
    """Minimal concrete record subclass used by these tests.

    ``record_kind`` is intentionally not redeclared so the parent's bounded-
    identifier pattern stays in force and tests can vary it freely.
    """


def _kwargs(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "record_kind": "test_record",
        "project_id": "proj-alpha",
        "created_by": "human",
    }
    base.update(overrides)
    return base


def test_frozen_model_rejects_unknown_fields_and_mutation():
    class _Value(FrozenModel):
        name: str

    value = _Value(name="x")
    with pytest.raises(ValidationError):
        _Value(name="x", surprise=True)
    with pytest.raises(ValidationError):
        value.name = "y"  # type: ignore[misc]


def test_record_base_derives_canonical_record_id_and_excludes_created_at():
    a = _Record(**_kwargs(created_at="2026-01-01T00:00:00Z"))
    b = _Record(**_kwargs(created_at="2027-12-31T00:00:00Z"))
    digest_a = canonical_record_id(a)
    digest_b = canonical_record_id(b)
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:") and len(digest_a) == len("sha256:") + 64


def test_record_id_must_equal_canonical_digest_when_supplied():
    correct = canonical_record_id(_Record(**_kwargs()))
    rec = _Record(**_kwargs(record_id=correct))
    assert rec.record_id == correct
    with pytest.raises(ValidationError):
        _Record(**_kwargs(record_id=_SHA))


def test_semantic_drift_changes_canonical_record_id():
    a = _Record(**_kwargs())
    b = _Record(**_kwargs(record_kind="other_kind"))
    assert canonical_record_id(a) != canonical_record_id(b)


def test_canonical_digest_is_sort_key_safe_and_unicode_stable():
    payload = {"b": 1, "a": "café-🎬", "nested": {"y": [1, 2], "x": True}}
    digest = canonical_digest(payload)
    expected = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    )
    assert digest == expected


def test_canonical_digest_rejects_non_finite_floats_via_model():
    class _Holder(FrozenModel):
        value: float

    with pytest.raises(ValidationError):
        _Holder(value=float("nan"))


def test_record_base_rejects_non_int_schema_version_and_bad_record_kind():
    for bad in (True, "1", 1.0):
        with pytest.raises(ValidationError):
            _Record(**_kwargs(schema_version=bad))
    for bad in ("UpperCase", "with space", "../traversal", "1lead", "x" * 65):
        with pytest.raises(ValidationError):
            _Record(**_kwargs(record_kind=bad))


def test_record_base_accepts_bounded_created_by_and_id_anchors():
    inner = _Record(
        **_kwargs(
            created_by="agent:worker-1",
            supersedes=_SHA_B,
            source_record_ids=(_SHA, _SHA_B),
        )
    )
    rec = _Record(
        **_kwargs(
            created_by="agent:worker-1",
            supersedes=_SHA_B,
            source_record_ids=(_SHA, _SHA_B),
            record_id=canonical_record_id(inner),
        )
    )
    assert rec.created_by == "agent:worker-1"
    assert rec.supersedes == _SHA_B
    assert rec.source_record_ids == (_SHA, _SHA_B)


def test_sha256_typed_alias_rejects_non_canonical_shape():
    with pytest.raises(ValidationError):
        _Record(**_kwargs(supersedes="0xdeadbeef"))


def test_bounded_code_rejects_prose_paths_and_metacharacters():
    assert BoundedCode("alpha_1.2:3-4") == "alpha_1.2:3-4"
    for bad in ("with space", "/abs/path", "../secret", "line\nbreak", "", "x" * 65, "1lead"):
        with pytest.raises(ValueError):
            BoundedCode(bad)


def test_location_violation_catches_absolute_home_url_traversal_and_control():
    for bad in (
        "/etc/passwd",
        "~/secret",
        "https://host/x",
        "file:///etc/x",
        "a/../b",
        "a//b",
        "C:\\secret",
        "ctrl\x00char",
    ):
        assert location_violation(bad) is not None
    assert location_violation("inputs/clip01.mp3") is None
    assert location_violation("rights/clip01.json") is None


def test_contract_error_returns_sound_contract_error_with_stable_code():
    err = contract_error("bad record", UNKNOWN_RECORD_FIELD)
    assert isinstance(err, SoundContractError)
    assert err.error_type == "validation_error"
    assert err.code == UNKNOWN_RECORD_FIELD
    assert err.suggested_action == {"auto_fix": False}
    assert str(err) == "bad record"


def test_stable_error_codes_are_distinct_strings():
    codes = {INVALID_RECORD, UNKNOWN_RECORD_FIELD, UNSAFE_LOCATION}
    assert codes == {"invalid_record", "unknown_record_field", "unsafe_location"}


def test_canonical_record_id_golden_vector_locks_serialization():
    rec = _Record(
        schema_version=1,
        record_kind="test_record",
        project_id="sonido-café-🎬",
        created_by="agent:worker_1",
        supersedes="sha256:" + "1" * 64,
        source_record_ids=("sha256:" + "2" * 64, "sha256:" + "3" * 64),
    )
    assert canonical_record_id(rec) == ("sha256:7e971cb7e228b87033c5f799f898496375c501b2de85a7042d96c9bed0e9abe8")
