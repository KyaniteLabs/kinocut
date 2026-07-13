"""Sound receipt and provenance contract (edit-receipt v1 + additive sound).

A sound receipt reuses the repository's edit-receipt v1 shape and adds a
single additive ``sound`` section. Absolute source paths, prompts, transcripts,
credentials, and subject PII are structurally excluded: they are unrepresentable
in the receipt's bounded codes and hashes. The whole section embeds under a
single additive ``sound`` key on an unchanged v1 receipt so the legacy shape
stays interoperable.

Design references (sonic-world design):
* Core contracts §"Receipt & Provenance".
* Errors, Privacy & Security — receipts/reports never disclose absolute paths,
  credentials, subject PII beyond the grant's declared scope, raw prompts, or
  transcripts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest, location_violation
from kinocut_sound.limits import (
    MAX_LOUDNESS_LUFS,
    MAX_LOUDNESS_RANGE_LU,
    MAX_TRUE_PEAK_DBTP,
    MIN_LOUDNESS_RANGE_LU,
    MIN_TIME_SECONDS,
)

# Revalidate embedded value objects so a payload that bypassed validation
# (e.g. via ``model_construct``) is fully re-checked at the receipt boundary.
_STRICT = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always")


def _strict_number(value: Any) -> Any:
    """Reject non-numeric (e.g. string ``"1.0"``) or boolean time/duration values."""

    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("time/duration must be a number, not a string or boolean")
    return value


def _strict_int(value: Any) -> Any:
    """Reject coerced versions (``True``, ``1.0``, ``"1"``) before strict-int fields."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be a strict integer")
    return value


class PreservationVerdict(StrEnum):
    """Whether a to-be-preserved element survived a transformation unchanged."""

    PRESERVED = "preserved"
    CHANGED = "changed"


class OrderedInput(FrozenModel):
    """One ordered input to a transformation, identified by content hash.

    ``safe_display_name`` is project-relative only: an absolute, home, or URL
    identifier is structurally rejected so a host filesystem layout cannot
    leak through the receipt.
    """

    model_config = _STRICT

    asset_id: Sha256
    input_hash: Sha256
    in_point: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    out_point: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    probed_duration: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    role: str = Field(min_length=1)
    safe_display_name: str = Field(min_length=1)

    @field_validator("role")
    @classmethod
    def _role_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("safe_display_name")
    @classmethod
    def _safe_display_name_is_project_relative(cls, value: str) -> str:
        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"safe_display_name {reason}")
        return value

    _num_in = field_validator("in_point", "out_point", "probed_duration", mode="before")(_strict_number)

    @model_validator(mode="after")
    def _points_ordered(self) -> OrderedInput:
        if (
            self.in_point is not None
            and self.out_point is not None
            and self.out_point <= self.in_point
        ):
            raise ValueError("out_point must be greater than in_point")
        if (
            self.in_point is not None
            and self.probed_duration is not None
            and self.in_point > self.probed_duration
        ):
            raise ValueError("in_point must not exceed probed_duration")
        if (
            self.out_point is not None
            and self.probed_duration is not None
            and self.out_point > self.probed_duration
        ):
            raise ValueError("out_point must not exceed probed_duration")
        return self


class Transformation(FrozenModel):
    """One tool/operation applied, with sanitized params and output identity."""

    model_config = _STRICT

    tool: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    params_hash: Sha256 | None = None
    toolchain_versions: tuple[str, ...] = ()
    output_duration: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    output_hash: Sha256 | None = None
    warnings: tuple[str, ...] = ()

    @field_validator("tool", "operation")
    @classmethod
    def _codes_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("toolchain_versions", "warnings")
    @classmethod
    def _code_lists_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        return value

    _num_out = field_validator("output_duration", mode="before")(_strict_number)


class PreservationProof(FrozenModel):
    """Evidence that an element expected identical was (or was not) preserved."""

    model_config = _STRICT

    expected: str = Field(min_length=1)
    method: str = Field(min_length=1)
    source_fingerprint: Sha256
    output_fingerprint: Sha256
    verdict: PreservationVerdict

    @field_validator("expected", "method")
    @classmethod
    def _codes_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class LoudnessVerification(FrozenModel):
    """Measured loudness/TP/LRA against a named preset, with pass/fail."""

    model_config = _STRICT

    preset: str = Field(min_length=1)
    integrated_lufs: float = Field(lt=MAX_LOUDNESS_LUFS)
    true_peak_dbtp: float = Field(lt=MAX_TRUE_PEAK_DBTP)
    lra_lu: float = Field(ge=MIN_LOUDNESS_RANGE_LU, le=MAX_LOUDNESS_RANGE_LU)
    within_tolerance: bool

    @field_validator("preset")
    @classmethod
    def _preset_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("integrated_lufs", "true_peak_dbtp", "lra_lu")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value


class SoundReceiptSection(FrozenModel):
    """The additive ``sound`` section carried on a v1 edit receipt.

    No subject identity, biometric material, raw prompt, or transcript is
    representable here: ``consent_grant_refs`` are opaque bounded ids, profile
    versions are bounded (id, version) pairs, and every other field is a hash
    or bounded code. The receipt is privacy-scrubbed by construction.
    """

    model_config = _STRICT

    plan_hash: Sha256
    profile_versions: tuple[tuple[str, int], ...] = ()
    consent_grant_refs: tuple[str, ...] = ()
    adapter_descriptors: tuple[str, ...] = ()
    loudness: LoudnessVerification
    ordered_inputs: tuple[OrderedInput, ...] = ()
    transformations: tuple[Transformation, ...] = ()
    preservation_proofs: tuple[PreservationProof, ...] = ()
    finding_ids: tuple[Sha256, ...] = ()
    review_artifact_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    human_review_required: bool

    @field_validator("consent_grant_refs", "adapter_descriptors", "review_artifact_refs", "warnings")
    @classmethod
    def _code_lists_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        return value

    @field_validator("profile_versions")
    @classmethod
    def _profile_versions_well_shaped(cls, value: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
        for entry in value:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValueError("profile_versions entries must be (id, version) tuples")
            pid, ver = entry
            BoundedCode(pid)
            if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
                raise ValueError("profile_versions version must be a positive integer")
        return value


class SoundReceipt(FrozenModel):
    """A v1 edit receipt with the additive ``sound`` section attached.

    The legacy fields match the repository's edit-receipt v1 shape; the new
    additive section rides under a single ``sound`` key. ``operation`` is a
    bounded code, ``output_hash`` is content-addressed, and the inputs are
    ordered. A serialized receipt never carries an absolute path, prompt, or
    transcript.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    operation: str = Field(min_length=1)
    normalized_parameters_hash: Sha256 | None = None
    inputs: tuple[OrderedInput, ...] = ()
    output_hash: Sha256
    output_duration: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    warnings: tuple[str, ...] = ()
    sound: SoundReceiptSection

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_strict_int(cls, value: Any) -> Any:
        return _strict_int(value)

    @field_validator("operation")
    @classmethod
    def _operation_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("warnings")
    @classmethod
    def _warnings_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        return value

    @classmethod
    def from_legacy(cls, legacy: dict[str, Any], section: SoundReceiptSection) -> SoundReceipt:
        """Build a :class:`SoundReceipt` from a legacy v1 dict plus the sound section.

        Privacy-safe: the legacy ``normalized_parameters`` dict is canonical-
        hashed into ``normalized_parameters_hash`` and the raw values are
        **never** stored on the receipt. If the legacy dict already carries a
        ``normalized_parameters_hash``, that explicit hash is preserved.
        """

        payload = dict(legacy)
        raw_params = payload.pop("normalized_parameters", None)
        if raw_params is not None and "normalized_parameters_hash" not in payload:
            payload["normalized_parameters_hash"] = canonical_digest(raw_params)
        payload["sound"] = section
        return cls.model_validate(payload)
