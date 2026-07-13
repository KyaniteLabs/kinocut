"""Bounded voice-consistency errors with stable public codes.

All failures surface through :class:`VoiceConsistencyError` so callers see
one uniform shape. Codes are stable public strings; downstream tooling
matches on them. Every suggested action is fail-closed (``auto_fix=False``)
— the consistency leaf never silently repairs a contract violation.
"""

from __future__ import annotations

from typing import Any

from kinocut_sound._errors import SoundContractError


class VoiceConsistencyError(SoundContractError):
    """Stable, fail-closed voice-consistency error."""


def consistency_error(message: str, code: str) -> VoiceConsistencyError:
    """Build a :class:`VoiceConsistencyError` with a stable code."""

    return VoiceConsistencyError(
        message,
        code=code,
        suggested_action={"auto_fix": False},
    )


def bounded_consistency_error(
    message: str,
    code: str,
    *,
    extra_action: dict[str, Any] | None = None,
) -> VoiceConsistencyError:
    """Build a :class:`VoiceConsistencyError` with a bounded remediation."""

    remediation = _REMEDIATIONS.get(code, "Retry with bounded inputs.")
    action: dict[str, Any] = {"auto_fix": False, "remediation": remediation}
    if extra_action is not None:
        for key, value in extra_action.items():
            if key == "auto_fix":
                action["auto_fix"] = False
            else:
                action[key] = value
    return VoiceConsistencyError(message, code=code, suggested_action=action)


# Stable error codes. Never renumber or repurpose.
CONSISTENCY_PROFILE_INVALID = "consistency_profile_invalid"
CONSISTENCY_LIBRARY_INVALID = "consistency_library_invalid"
CONSISTENCY_D42_UNAVAILABLE = "consistency_d42_unavailable"
CONSISTENCY_METRIC_INVALID = "consistency_metric_invalid"
CONSISTENCY_DRIFT_DETECTED = "consistency_drift_detected"
CONSISTENCY_COLLISION_DETECTED = "consistency_collision_detected"
CONSISTENCY_REGENERATION_FAILED = "consistency_regeneration_failed"


_REMEDIATIONS: dict[str, str] = {
    CONSISTENCY_PROFILE_INVALID: "Supply a valid VoiceProfile with bounded ids.",
    CONSISTENCY_LIBRARY_INVALID: "Use a valid profile id and monotonic version.",
    CONSISTENCY_D42_UNAVAILABLE: "Inject a FakeD42Port or configure a real D42 binding.",
    CONSISTENCY_METRIC_INVALID: "Provide bounded audio hashes and a configured D42 port.",
    CONSISTENCY_DRIFT_DETECTED: "Review drift events and run realign() if intended.",
    CONSISTENCY_COLLISION_DETECTED: "Reassign colliding slots or tighten distinctiveness threshold.",
    CONSISTENCY_REGENERATION_FAILED: "Verify the planner, roster, and episode plans are valid.",
}
