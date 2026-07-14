"""Tests for the shared AI-video record base, typed ids, and canonical hashing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import AssetId, RecordBase, Sha256, canonical_record_id
from kinocut.contracts._errors import (
    INVALID_RECORD,
    RECORD_SUPERSESSION_CYCLE,
    STALE_APPROVAL_FINGERPRINT,
    UNKNOWN_RECORD_FIELD,
    contract_error,
)
from tests.contracts_fixtures import valid_record_kwargs

_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64


def test_record_id_excludes_created_at_but_binds_semantics():
    kwargs = valid_record_kwargs()
    a = RecordBase(**kwargs, created_at="2026-01-01T00:00:00Z")
    b = RecordBase(**kwargs, created_at="2027-02-02T00:00:00Z")
    assert canonical_record_id(a) == canonical_record_id(b)  # created_at excluded
    assert canonical_record_id(a).startswith("sha256:")
    assert len(canonical_record_id(a)) == len("sha256:") + 64


def test_record_id_may_carry_its_own_canonical_digest():
    # A stored record_id must equal the canonical digest (fail-closed identity),
    # and it never participates in the digest computation itself.
    kwargs = valid_record_kwargs()
    without = RecordBase(**kwargs)
    digest = canonical_record_id(without)
    with_id = RecordBase(**kwargs, record_id=digest)
    assert canonical_record_id(with_id) == digest
    assert with_id.record_id == digest


def test_record_id_changes_when_semantics_change():
    a = RecordBase(**valid_record_kwargs())
    b = RecordBase(**valid_record_kwargs(record_kind="other_kind"))
    assert canonical_record_id(a) != canonical_record_id(b)


def test_written_record_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RecordBase.model_validate(
            {
                "schema_version": 1,
                "record_kind": "x",
                "project_id": "p",
                "created_by": "human",
                "surprise": True,
            }
        )


def test_record_base_is_frozen():
    record = RecordBase(**valid_record_kwargs())
    with pytest.raises(ValidationError):
        record.project_id = "mutated"


def test_sha256_typed_ids_reject_bad_pattern():
    with pytest.raises(ValidationError):
        RecordBase(**valid_record_kwargs(), record_id="not-a-hash")
    with pytest.raises(ValidationError):
        RecordBase(**valid_record_kwargs(), supersedes="sha256:XYZ")


def test_sha256_and_asset_id_accept_canonical_digests():
    kwargs = valid_record_kwargs()
    seed = RecordBase(**kwargs, supersedes=_SHA_B, source_record_ids=(_SHA, _SHA_B))
    digest = canonical_record_id(seed)
    record = RecordBase(
        **kwargs,
        record_id=digest,
        supersedes=_SHA_B,
        source_record_ids=(_SHA, _SHA_B),
    )
    assert record.record_id == digest
    assert record.source_record_ids == (_SHA, _SHA_B)
    # AssetId shares the Sha256 shape and both are importable typed aliases.
    assert Sha256 is not None and AssetId is not None


def test_created_by_must_be_bounded_role():
    for actor in ("human", "agent", "tool", "agent:planner-1", "tool:ffmpeg_6.0"):
        RecordBase(**valid_record_kwargs(created_by=actor))
    for bad in ("robot", "human; rm -rf", "agent:" + "x" * 200, ""):
        with pytest.raises(ValidationError):
            RecordBase(**valid_record_kwargs(created_by=bad))


def test_contract_error_maps_validation_code():
    err = contract_error("bad record", UNKNOWN_RECORD_FIELD)
    assert err.error_type == "validation_error"
    assert err.code == UNKNOWN_RECORD_FIELD
    assert err.suggested_action == {"auto_fix": False}
    assert str(err) == "bad record"


def test_stable_error_codes_are_distinct():
    codes = {
        INVALID_RECORD,
        UNKNOWN_RECORD_FIELD,
        STALE_APPROVAL_FINGERPRINT,
        RECORD_SUPERSESSION_CYCLE,
    }
    assert codes == {
        "invalid_record",
        "unknown_record_field",
        "stale_approval_fingerprint",
        "record_supersession_cycle",
    }


# --- Reviewer-mandated prerequisite regressions (fail-closed hardening) -------
# These witness RED against the current _common.py and are fixed in Task 3.


class _FloatBearingRecord(RecordBase):
    """A float-carrying subclass used to prove non-finite floats are rejected."""

    measure: float


def test_float_fields_reject_non_finite_for_canonical_stability():
    # allow_inf_nan must be False so NaN/Inf can never enter canonical JSON and
    # silently diverge record identity across serializers.
    _FloatBearingRecord(**valid_record_kwargs(), measure=1.5)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            _FloatBearingRecord(**valid_record_kwargs(), measure=bad)


def test_record_kind_must_be_a_safe_bounded_identifier():
    for good in ("clip_verdict", "asset_record", "x", "a1_b2"):
        RecordBase(**valid_record_kwargs(record_kind=good))
    for bad in (
        "../evil",
        "/abs/path",
        "with space",
        "UpperCase",
        "bad-dash",
        "nul\x00byte",
        "1leading",
        "x" * 65,
    ):
        with pytest.raises(ValidationError):
            RecordBase(**valid_record_kwargs(record_kind=bad))


def test_supplied_record_id_must_equal_canonical_digest():
    kwargs = valid_record_kwargs()
    correct = canonical_record_id(RecordBase(**kwargs))
    RecordBase(**kwargs, record_id=correct)  # matching id accepted
    with pytest.raises(ValidationError):
        RecordBase(**kwargs, record_id=_SHA)  # sha-shaped but not the real digest


def test_schema_version_rejects_non_int_coercion():
    RecordBase(**valid_record_kwargs(schema_version=1))
    for bad in (True, "1", 1.0):
        with pytest.raises(ValidationError):
            RecordBase(**valid_record_kwargs(schema_version=bad))


def test_canonical_id_golden_vector_locks_unicode_and_nested_serialization():
    # A pinned canonical vector over Unicode + nested content. Any drift in
    # serialization (key order, separators, encoding) breaks this assertion.
    rec = RecordBase(
        schema_version=1,
        record_kind="clip_verdict",
        project_id="proyecto-café-🎬",
        created_by="agent:worker_1",
        supersedes="sha256:" + "1" * 64,
        source_record_ids=("sha256:" + "2" * 64, "sha256:" + "3" * 64),
    )
    assert canonical_record_id(rec) == ("sha256:6a17ce367257017a4db24d04bf23d678242ef815d94dc2360a956582e27ffc11")
