"""Tests for ``ProtectedElement``, ``ElementType``, ``DurationPolicy`` (design §4.6).

A protected element binds an element type, exact dependency fingerprint,
allowed operations, and an explicit duration policy. There is deliberately no
force flag: agents can never bypass protection.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.protection import (
    DurationPolicy,
    ElementType,
    ProtectedElement,
)
from tests.contracts_fixtures import protection_kwargs


def test_protected_element_has_no_force_flag():
    fields = ProtectedElement.model_fields
    assert "force" not in fields
    # No bypass/override boolean of any name may exist.
    assert not any("force" in name or "override" in name or "bypass" in name for name in fields)


def test_element_type_is_closed():
    assert {e.value for e in ElementType} == {
        "source_asset",
        "audio_stream",
        "clip_range",
        "timeline_range",
        "graphic",
        "subtitle_set",
        "timing_map",
        "mix",
        "render_parameter_set",
    }


def test_duration_policy_is_closed():
    assert {p.value for p in DurationPolicy} == {
        "preserve",
        "pad",
        "loop",
        "trim",
        "shortest",
    }


def test_protected_element_is_a_record():
    element = ProtectedElement(**protection_kwargs())
    assert isinstance(element, RecordBase)
    assert canonical_record_id(element).startswith("sha256:")


def test_dependency_fingerprint_must_be_sha256():
    with pytest.raises(ValidationError):
        ProtectedElement(**protection_kwargs(dependency_fingerprint="not-a-hash"))


def test_protected_element_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProtectedElement(**protection_kwargs(force=True))


def test_protected_element_is_frozen():
    element = ProtectedElement(**protection_kwargs())
    with pytest.raises(ValidationError):
        element.duration_policy = DurationPolicy.SHORTEST
