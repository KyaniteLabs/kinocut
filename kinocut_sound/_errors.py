"""Stable typed errors and frozen contract codes for ``kinocut_sound``.

All contract validation failures surface through :class:`SoundContractError`
so callers see one uniform shape. Codes are stable public strings; downstream
modules and adapters match on them. ``contract_error`` always reports a
non-auto-fixing suggested action — contract violations require an explicit
human or caller correction, never a silent repair.
"""

from __future__ import annotations

from typing import Any


class SoundContractError(Exception):
    """Base error for every ``kinocut_sound`` contract violation.

    A contract error always carries a stable ``code``, an ``error_type``
    (currently always ``validation_error`` because every failure is a caller
    input problem), and a ``suggested_action`` whose ``auto_fix`` flag is
    False — the sidecar never silently repairs a contract violation.
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "validation_error",
        code: str,
        suggested_action: dict[str, Any] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.error_type = error_type
        self.code = code
        self.suggested_action = suggested_action if suggested_action is not None else {"auto_fix": False}
        self.details = details
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return the public error payload — never includes host paths or secrets."""

        payload: dict[str, Any] = {
            "type": self.error_type,
            "code": self.code,
            "message": str(self),
            "suggested_action": self.suggested_action,
        }
        if self.details:
            payload["details"] = self.details
        return payload


# Stable contract error codes (design §"Receipt & Provenance" / §"Errors, Privacy
# & Security"). Never renumber or repurpose; downstream modules match on them.
INVALID_RECORD = "invalid_record"
UNKNOWN_RECORD_FIELD = "unknown_record_field"
UNSAFE_LOCATION = "unsafe_location"
INVALID_PLAN = "invalid_plan"


class SoundPlanValidationError(SoundContractError, ValueError):
    """A SoundPlan payload failed validation.

    ``details`` lists ``{"loc", "msg", "type"}`` for each failing field. Input
    values are deliberately left out: they can carry host paths or prompts.
    Subclasses ``ValueError`` so pre-existing ``except ValueError`` callers
    keep working.
    """


def contract_error(message: str, code: str) -> SoundContractError:
    """Build a :class:`SoundContractError` with a stable code and no auto-fix."""

    return SoundContractError(message, code=code, suggested_action={"auto_fix": False})
