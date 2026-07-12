"""Store-boundary hardening for the project store (Plan 00 Task 3 follow-up).

The public store adapters are a trust boundary. Two guarantees are tested here:

1. **Uniform error shape** — reading a corrupt/unknown-field record never leaks a
   raw Pydantic ``ValidationError`` (nor a bare ``ValueError``); it surfaces as
   the stable contract :class:`MCPVideoError` with code ``invalid_record``.
2. **Independent path defense** — the store rejects unsafe location fields
   (absolute, traversal, URL-scheme, NUL/control-char, empty, empty components)
   *at append time*, independently of any domain-model validator. This holds
   even when a record is smuggled past model validation via ``model_copy`` —
   proving the guard does not rely on ``AssetRecord`` staying hardened.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as PydanticValidationError

from kinocut.contracts._errors import INVALID_RECORD, UNKNOWN_RECORD_FIELD
from kinocut.contracts.asset import AssetRecord
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project, read_records
from tests.contracts_fixtures import asset_record_kwargs


def _asset(project, **overrides) -> AssetRecord:
    return AssetRecord(**asset_record_kwargs(project_id=project.project_id, **overrides))


def _tampered_location(project, value: str) -> AssetRecord:
    """A valid asset record whose location is swapped in *after* validation."""

    return _asset(project).model_copy(update={"original_location": value})


# ---- 1. Uniform error shape on read ---------------------------------------


def test_read_records_wraps_unknown_field_as_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_text(
        json.dumps({"record_kind": "clip_verdict", "surprise": True}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MCPVideoError) as excinfo:
        read_records(proj, "clip_verdict")
    assert excinfo.value.code == UNKNOWN_RECORD_FIELD
    assert not isinstance(excinfo.value, PydanticValidationError)
    assert not isinstance(excinfo.value, ValueError)


def test_read_records_wraps_malformed_json_as_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_text("{not valid json\n", encoding="utf-8")
    with pytest.raises(MCPVideoError) as excinfo:
        read_records(proj, "clip_verdict")
    assert excinfo.value.code == INVALID_RECORD


# ---- 2. Independent path defense on append --------------------------------


@pytest.mark.parametrize(
    "bad_location",
    [
        "/etc/passwd",  # absolute
        "~/secrets.txt",  # home
        "\\\\server\\share",  # UNC / backslash absolute
        "C:\\Windows",  # drive letter
        "../../escape.mp4",  # traversal
        "a/../../escape.mp4",  # interior traversal
        "http://evil.test/x.mp4",  # URL scheme
        "file:///etc/passwd",  # file URL
        "data:text/plain;base64,AA",  # data URL
        "a\x00b.mp4",  # NUL byte
        "a\tb.mp4",  # control char
        "",  # empty
        "a//b.mp4",  # empty component
    ],
)
def test_append_rejects_unsafe_location_independent_of_model(tmp_path, bad_location):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, _tampered_location(proj, bad_location))
    assert excinfo.value.code == INVALID_RECORD
    assert not isinstance(excinfo.value, PydanticValidationError)
    # The rejected write never touched the store.
    assert read_records(proj, "asset_record") == []


def test_append_accepts_safe_project_relative_location(tmp_path):
    proj = open_project(tmp_path / "proj")
    stored = append_record(proj, _asset(proj, original_location="inputs/clip01.mp4"))
    assert stored.record_id is not None
    assert read_records(proj, "asset_record")[0].original_location == "inputs/clip01.mp4"


def test_append_also_guards_secondary_path_field(tmp_path):
    # usage_rights_evidence_ref is path-bearing too; tamper it past the model.
    proj = open_project(tmp_path / "proj")
    tampered = _asset(proj).model_copy(update={"usage_rights_evidence_ref": "/abs/evidence.json"})
    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, tampered)
    assert excinfo.value.code == INVALID_RECORD
