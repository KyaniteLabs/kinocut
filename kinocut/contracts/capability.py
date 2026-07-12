"""``CapabilityReport`` and advisory-only ``NextAction`` (design §4.10, Task 6).

A capability report is a *structured* contract, not free help text: a bounded
capability code, per-surface availability booleans (MCP / Python / CLI), bounded
supported-format and dependency codes, a closed availability state, and — only
when not fully available — a bounded reason code plus short remediation text.

A next-action is advisory *only*: an action code, a short summary, at most one
bounded and sanitized command *template* (which starts with ``kino`` and can
never carry a real path, shell metacharacter, or execute), and the record ids
that block it. Nothing here is an execution hook.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import StrictBool, field_validator, model_validator

from kinocut.contracts._common import Sha256, ValueObject

# A bounded lowercase code: capability ids, action/reason codes, formats, deps.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
# Short advisory human text: bounded, no control chars, host paths, URLs, or
# shell metacharacters — spaces and ordinary punctuation are fine.
_ADVISORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.\-_'()]{0,199}$")
# A sanitized command *template*: ``kino`` followed by space-separated tokens,
# each token EITHER a safe word (no ``/`` or shell metacharacters) OR a single
# well-formed ``<name>`` placeholder. Stray, adjacent, empty, or glued brackets
# cannot form a valid token. At least one placeholder is required separately, so
# a fully concrete runnable command is refused and the template stays inert.
_TEMPLATE_PART = r"(?:[a-z0-9_.:=-]+|<[a-z][a-z_]*>)"
_COMMAND_TEMPLATE_RE = re.compile(rf"^kino {_TEMPLATE_PART}(?: {_TEMPLATE_PART})*$")


def _reject_non_code(value: str) -> str:
    if not _CODE_RE.match(value):
        raise ValueError("value must be a bounded lowercase code")
    return value


def _reject_non_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    for value in values:
        _reject_non_code(value)
    return values


def _reject_unsafe_advisory(value: str) -> str:
    if not _ADVISORY_RE.match(value):
        raise ValueError("advisory text must be short and free of paths, URLs, or metacharacters")
    return value


class AvailabilityState(StrEnum):
    """The closed availability posture of a capability on the current host."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class SurfaceAvailability(ValueObject):
    """Whether a capability is reachable on each public surface (strict booleans)."""

    mcp: StrictBool
    python: StrictBool
    cli: StrictBool


class CapabilityReport(ValueObject):
    """A structured description of one capability's availability (design §4.10)."""

    capability_id: str
    surfaces: SurfaceAvailability
    supported_formats: tuple[str, ...] = ()
    required_deps: tuple[str, ...] = ()
    optional_deps: tuple[str, ...] = ()
    availability: AvailabilityState
    reason_code: str | None = None
    remediation: str | None = None

    _code_capability = field_validator("capability_id")(_reject_non_code)
    _code_formats = field_validator("supported_formats")(_reject_non_codes)
    _code_required = field_validator("required_deps")(_reject_non_codes)
    _code_optional = field_validator("optional_deps")(_reject_non_codes)

    @field_validator("reason_code")
    @classmethod
    def _reason_is_code(cls, value: str | None) -> str | None:
        return _reject_non_code(value) if value is not None else value

    @field_validator("remediation")
    @classmethod
    def _remediation_is_advisory(cls, value: str | None) -> str | None:
        return _reject_unsafe_advisory(value) if value is not None else value

    @model_validator(mode="after")
    def _availability_coherence(self) -> CapabilityReport:
        """Surface booleans, reason, and remediation must match the availability state.

        ``available`` ⇒ every surface true, no reason/remediation. ``unavailable``
        ⇒ every surface false, with reason + remediation. ``degraded`` ⇒ a mix of
        surfaces (some true, some false), with reason + remediation. Duplicate
        formats/dependencies and required/optional overlap are rejected.
        """

        surfaces = (self.surfaces.mcp, self.surfaces.python, self.surfaces.cli)
        has_evidence = self.reason_code is not None and self.remediation is not None
        no_evidence = self.reason_code is None and self.remediation is None
        if self.availability is AvailabilityState.AVAILABLE:
            if not all(surfaces) or not no_evidence:
                raise ValueError("available requires all surfaces true and no reason/remediation")
        elif self.availability is AvailabilityState.UNAVAILABLE:
            if any(surfaces) or not has_evidence:
                raise ValueError("unavailable requires all surfaces false with reason + remediation")
        elif all(surfaces) or not any(surfaces) or not has_evidence:  # DEGRADED
            raise ValueError("degraded requires mixed surfaces with reason + remediation")

        if len(set(self.supported_formats)) != len(self.supported_formats):
            raise ValueError("supported_formats must be unique")
        required, optional = set(self.required_deps), set(self.optional_deps)
        if len(required) != len(self.required_deps) or len(optional) != len(self.optional_deps):
            raise ValueError("dependency codes must be unique within required and optional")
        if required & optional:
            raise ValueError("a dependency may not be both required and optional")
        return self


class NextAction(ValueObject):
    """A single advisory next step — never an autonomy grant (design §4.10)."""

    action_code: str
    summary: str
    command_template: str | None = None
    blocking_record_ids: tuple[Sha256, ...] = ()

    _code_action = field_validator("action_code")(_reject_non_code)
    _advisory_summary = field_validator("summary")(_reject_unsafe_advisory)

    @field_validator("blocking_record_ids")
    @classmethod
    def _blocking_ids_unique(cls, value: tuple[Sha256, ...]) -> tuple[Sha256, ...]:
        if len(set(value)) != len(value):
            raise ValueError("blocking_record_ids must be unique")
        return value

    @field_validator("command_template")
    @classmethod
    def _template_is_bounded_and_inert(cls, value: str | None) -> str | None:
        """A command template is a bounded ``kino`` advisory string, never runnable."""

        if value is not None:
            if not _COMMAND_TEMPLATE_RE.match(value):
                raise ValueError("command_template must be a bounded 'kino ...' advisory template")
            if "<" not in value:  # a concrete runnable command is not a template
                raise ValueError("command_template must contain at least one <placeholder>")
        return value
