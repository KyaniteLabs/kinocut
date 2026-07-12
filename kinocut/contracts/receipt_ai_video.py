"""Additive ``ai_video`` receipt section contracts (design §4.7, Plan 00 Task 5).

These value objects describe, for a produced artifact, exactly what went in
(``OrderedInput``), what transformed it (``Transformation``), what was proven
preserved (``PreservationProof``), and the review/approval linkage — all by id,
hash, enum, and number only. Numbers are nonnegative, ordered, and coherent.
Every identity-like free-text field (role, tool, operation, method, expected,
duration policy, project id, toolchain versions, warnings) is a *closed bounded
code* — alphanumerics plus ``_ . : -`` only — so a host path, URL, secret, or
raw-prompt prose is structurally unrepresentable and can never serialize. The
whole :class:`AiVideoReceiptSection` embeds under a single additive ``ai_video``
key on an unchanged legacy receipt.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from kinocut.contracts._common import AssetId, Sha256, ValueObject

# A bounded identifier: alphanumeric start, then alnum / underscore / dot /
# colon / hyphen, up to 64 chars. No spaces, slashes, or control characters —
# arbitrary prose and host paths simply cannot match.
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def _reject_non_code(value: str) -> str:
    """Field-validator body: require a bounded code, not prose or a path."""

    if not _CODE_RE.match(value):
        raise ValueError("value must be a bounded code (no spaces, paths, URLs, or prose)")
    return value


def _reject_non_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    """Field-validator body for a tuple of bounded codes."""

    for value in values:
        _reject_non_code(value)
    return values


def _strict_contract_version(value: Any) -> Any:
    """Reject coerced versions (``True``, ``1.0``, ``"1"``) before the literal."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("contract_version must be the integer 1")
    return value

# A bounded identifier: alphanumeric start, then alnum / underscore / dot /
# colon / hyphen, up to 64 chars. No spaces, slashes, or control characters —
# arbitrary prose and host paths simply cannot match.
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def _reject_non_code(value: str) -> str:
    """Field-validator body: require a bounded code, not prose or a path."""

    if not _CODE_RE.match(value):
        raise ValueError("value must be a bounded code (no spaces, paths, URLs, or prose)")
    return value


def _reject_non_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    """Field-validator body for a tuple of bounded codes."""

    for value in values:
        _reject_non_code(value)
    return values


def _strict_contract_version(value: Any) -> Any:
    """Reject coerced versions (``True``, ``1.0``, ``"1"``) before the literal."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("contract_version must be the integer 1")
    return value


def _strict_number(value: Any) -> Any:
    """Reject non-numeric (e.g. string ``"1.0"``) or boolean time/duration values."""

    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("time/duration must be a number, not a string or boolean")
    return value


def _strict_number(value: Any) -> Any:
    """Reject non-numeric (e.g. string ``"1.0"``) or boolean time/duration values."""

    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("time/duration must be a number, not a string or boolean")
    return value


class PreservationVerdict(StrEnum):
    """Whether a to-be-preserved element survived a transformation unchanged."""

    PRESERVED = "preserved"
    CHANGED = "changed"


class OrderedInput(ValueObject):
    """One ordered input to a transformation, identified by content hash."""

    asset_id: AssetId
    input_hash: Sha256
    in_point: float | None = Field(default=None, ge=0.0)
    out_point: float | None = Field(default=None, ge=0.0)
    probed_duration: float | None = Field(default=None, ge=0.0)
    role: str = Field(min_length=1)

    _safe_role = field_validator("role")(_reject_non_code)
    _num_in = field_validator("in_point", "out_point", "probed_duration", mode="before")(_strict_number)

    @model_validator(mode="after")
    def _points_ordered(self) -> OrderedInput:
        """A present in/out pair is ordered and stays within the probed duration."""

        if self.in_point is not None and self.out_point is not None and self.out_point <= self.in_point:
            raise ValueError("out_point must be greater than in_point")
        if self.in_point is not None and self.probed_duration is not None and self.in_point > self.probed_duration:
            raise ValueError("in_point must not exceed probed_duration")
        if self.out_point is not None and self.probed_duration is not None and self.out_point > self.probed_duration:
            raise ValueError("out_point must not exceed probed_duration")
        return self


class Transformation(ValueObject):
    """One tool/operation applied, with sanitized params and output identity."""

    tool: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    params_hash: Sha256 | None = None
    toolchain_versions: tuple[str, ...] = ()
    output_duration: float | None = Field(default=None, ge=0.0)
    output_hash: Sha256 | None = None
    warnings: tuple[str, ...] = ()

    _safe_tool = field_validator("tool")(_reject_non_code)
    _safe_operation = field_validator("operation")(_reject_non_code)
    _safe_versions = field_validator("toolchain_versions")(_reject_non_codes)
    _safe_warnings = field_validator("warnings")(_reject_non_codes)
    _num_out = field_validator("output_duration", mode="before")(_strict_number)


class PreservationProof(ValueObject):
    """Evidence that an element expected to be identical was (or was not)."""

    expected: str = Field(min_length=1)
    method: str = Field(min_length=1)
    source_fingerprint: Sha256
    output_fingerprint: Sha256
    verdict: PreservationVerdict

    _safe_expected = field_validator("expected")(_reject_non_code)
    _safe_method = field_validator("method")(_reject_non_code)


class AiVideoReceiptSection(ValueObject):
    """The additive ``ai_video`` section carried on a legacy receipt (design §4.7)."""

    contract_version: Literal[1] = 1
    project_id: str = Field(min_length=1)
    acceptance_spec_id: Sha256 | None = None
    ordered_inputs: tuple[OrderedInput, ...] = ()
    transformations: tuple[Transformation, ...] = ()
    duration_policy: str = Field(min_length=1)
    preservation_proofs: tuple[PreservationProof, ...] = ()
    finding_ids: tuple[Sha256, ...] = ()
    review_artifact_ids: tuple[Sha256, ...] = ()
    approval_state_id: Sha256 | None = None
    warnings: tuple[str, ...] = ()

    _strict_version = field_validator("contract_version", mode="before")(_strict_contract_version)
    _safe_policy = field_validator("duration_policy")(_reject_non_code)
    _safe_project = field_validator("project_id")(_reject_non_code)
    _safe_warnings = field_validator("warnings")(_reject_non_codes)
