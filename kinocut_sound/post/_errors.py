"""Bounded errors for the ``kinocut_sound.post`` sidecar package.

Post-chain failures surface through :class:`PostError` (a thin sibling of
``kinocut_sound.SoundContractError``) so callers see one stable shape with a
non-auto-fixing suggested action. Codes are stable public strings.

These errors never wrap raw provider stderr, host paths, or secrets — the
sidecar boundary keeps subprocess detail internal and surfaces only a bounded
``code`` plus an advisory ``remediation``.
"""

from __future__ import annotations

from typing import Any


class PostError(Exception):
    """Base error for every ``kinocut_sound.post`` failure.

    Mirrors :class:`kinocut_sound.SoundContractError`: stable ``code``, an
    ``error_type`` (currently always ``validation_error`` because every
    failure is a caller input problem unless flagged otherwise), and a
    ``suggested_action`` whose ``auto_fix`` flag is False. Raw provider
    stderr, host paths, and filter strings are never embedded.
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "validation_error",
        code: str,
        suggested_action: dict[str, Any] | None = None,
    ) -> None:
        self.error_type = error_type
        self.code = code
        self.suggested_action = suggested_action if suggested_action is not None else {"auto_fix": False}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return the public error payload — never includes host paths or secrets."""

        return {
            "type": self.error_type,
            "code": self.code,
            "message": str(self),
            "suggested_action": self.suggested_action,
        }


def post_error(message: str, code: str) -> PostError:
    """Build a :class:`PostError` with a stable code and no auto-fix."""

    return PostError(message, code=code, suggested_action={"auto_fix": False})


# Stable post error codes. Never renumber or repurpose; downstream modules and
# callers match on them.
POST_INVALID_PARAM = "invalid_post_param"
POST_OVER_LIMIT = "post_param_over_limit"
POST_PROCESSING_FAILED = "post_processing_failed"
POST_DEPENDENCY_MISSING = "post_dependency_missing"
POST_TIMEOUT = "post_timeout"
POST_PRESET_UNKNOWN = "post_preset_unknown"
POST_CLIP_MISSING = "post_clip_missing"
POST_OVERRUN = "post_overrun"


__all__ = [
    "POST_CLIP_MISSING",
    "POST_DEPENDENCY_MISSING",
    "POST_INVALID_PARAM",
    "POST_OVERRUN",
    "POST_OVER_LIMIT",
    "POST_PRESET_UNKNOWN",
    "POST_PROCESSING_FAILED",
    "POST_TIMEOUT",
    "PostError",
    "post_error",
]
