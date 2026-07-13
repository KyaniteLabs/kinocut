"""Bounded world/ambience contract errors for the S8 leaf.

All world-package validation failures surface through :class:`WorldError`,
which subclasses :class:`kinocut_sound._errors.SoundContractError` so callers
see one uniform error shape with a stable ``code`` and a non-auto-fixing
suggested action. Codes are stable public strings; downstream stages (S9
assembly, S13 host joins) match on them.
"""

from __future__ import annotations

from typing import Any

from kinocut_sound._errors import SoundContractError


class WorldError(SoundContractError):
    """Fail-closed world/ambience contract error (S8 leaf)."""


def world_error(message: str, code: str) -> WorldError:
    """Build a :class:`WorldError` with a stable code and no auto-fix."""

    return WorldError(message, code=code, suggested_action={"auto_fix": False})


# Stable world-package error codes. Never renumber or repurpose; the S9/S13
# leaves and downstream tests match on these strings.
UNLICENSED_ASSET = "unlicensed_asset"
UNKNOWN_ASSET = "unknown_asset"
UNKNOWN_FOLEY_CUE = "unknown_foley_cue"
LAYER_STACK_INVALID = "layer_stack_invalid"
LOOP_INVALID = "loop_invalid"
PRESET_INVALID = "preset_invalid"
AUDITION_INVALID = "audition_invalid"
PORT_UNAVAILABLE = "port_unavailable"
CATALOG_INVALID = "catalog_invalid"


def world_error_dict(code: str, message: str) -> dict[str, Any]:
    """Return the public error payload shape for world errors."""

    return {
        "type": "validation_error",
        "code": code,
        "message": message,
        "suggested_action": {"auto_fix": False},
    }
