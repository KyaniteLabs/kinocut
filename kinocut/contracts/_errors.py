"""Stable error codes for the AI-video contract layer.

All contract validation failures surface through :class:`MCPVideoError`
(``kinocut/errors.py``) so callers see one uniform error shape. Codes are
frozen public strings; downstream waves match on them.
"""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError

# Stable contract error codes (design §4). Never renumber or repurpose.
INVALID_RECORD = "invalid_record"
UNKNOWN_RECORD_FIELD = "unknown_record_field"
STALE_APPROVAL_FINGERPRINT = "stale_approval_fingerprint"
RECORD_SUPERSESSION_CYCLE = "record_supersession_cycle"
PROTECTED_ELEMENT_CHANGE = "protected_element_change"


def contract_error(message: str, code: str) -> MCPVideoError:
    """Build a validation-type :class:`MCPVideoError` with a stable contract code.

    ``suggested_action`` is always non-auto-fixing: contract violations require
    an explicit human or caller correction, never a silent repair.
    """

    suggested_action: dict[str, Any] = {"auto_fix": False}
    return MCPVideoError(
        message,
        error_type="validation_error",
        code=code,
        suggested_action=suggested_action,
    )
