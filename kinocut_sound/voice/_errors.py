"""Bounded voice-leaf errors with stable public codes.

All voice-leaf failures surface through :class:`VoiceError` (a
:class:`kinocut_sound.SoundContractError` subclass) so callers see one uniform
shape alongside the rest of the sidecar. Codes are stable public strings;
downstream tooling matches on them. Every suggested action is fail-closed
(``auto_fix=False``) — the voice leaf never silently repairs a contract
violation, never falls back to a different voice, and never reaches for a
cloud provider implicitly.
"""

from __future__ import annotations

from typing import Any

from kinocut_sound._errors import SoundContractError


class VoiceError(SoundContractError):
    """Stable, fail-closed voice-leaf error."""


def voice_error(message: str, code: str) -> VoiceError:
    """Build a :class:`VoiceError` with a stable code and no auto-fix."""

    return VoiceError(message, code=code, suggested_action={"auto_fix": False})


# Stable voice-leaf error codes. Never renumber or repurpose; downstream
# modules and adapters match on them.
ROSTER_UNKNOWN = "roster_unknown"
ROSTER_INVALID = "roster_invalid"
ROSTER_EXCEEDS_CEILING = "roster_exceeds_ceiling"
PROSODY_OUT_OF_RANGE = "prosody_out_of_range"
EMOTION_OUT_OF_RANGE = "emotion_out_of_range"
PRONUNCIATION_INVALID = "pronunciation_invalid"
VOICE_UNAVAILABLE = "voice_unavailable"
VOICE_RENDER_FAILED = "voice_render_failed"
BATCH_PLAN_INVALID = "batch_plan_invalid"
CLOUD_NOT_ALLOWED = "cloud_not_allowed"
ADAPTER_INPUT_INVALID = "adapter_input_invalid"
ADAPTER_OUTPUT_INVALID = "adapter_output_invalid"
ADAPTER_TIMEOUT = "adapter_timeout"
ADAPTER_CANCELLED = "adapter_cancelled"
ADAPTER_LIMIT_EXCEEDED = "adapter_limit_exceeded"


# Bounded advisory remediations (must satisfy ADVISORY_RE in validation.py).
_REMEDIATIONS: dict[str, str] = {
    ROSTER_UNKNOWN: "Select a roster slot id compiled into the voice roster.",
    ROSTER_INVALID: "Repair the voice roster configuration before rendering.",
    ROSTER_EXCEEDS_CEILING: "Trim the voice roster to its declared ceiling.",
    PROSODY_OUT_OF_RANGE: "Clamp prosody overrides to the plan envelope.",
    EMOTION_OUT_OF_RANGE: "Clamp emotion intensity to the plan envelope.",
    PRONUNCIATION_INVALID: "Supply a bounded IPA override keyed by term hash.",
    VOICE_UNAVAILABLE: "Install or repair the local TTS adapter dependency.",
    VOICE_RENDER_FAILED: "Retry with bounded inputs or a different slot.",
    BATCH_PLAN_INVALID: "Supply a validated SoundPlan with unique line ids.",
    CLOUD_NOT_ALLOWED: "Confirm cloud opt-in and authorization before use.",
    ADAPTER_INPUT_INVALID: "Provide bounded line, slot, and prosody inputs.",
    ADAPTER_OUTPUT_INVALID: "Discard and re-render with bounded inputs.",
    ADAPTER_TIMEOUT: "Reduce batch size or raise the bounded timeout.",
    ADAPTER_CANCELLED: "Retry the cancelled render with the same inputs.",
    ADAPTER_LIMIT_EXCEEDED: "Reduce batch size below the declared ceiling.",
}


def bounded_voice_error(
    message: str,
    code: str,
    *,
    extra_action: dict[str, Any] | None = None,
) -> VoiceError:
    """Build a :class:`VoiceError` with a bounded advisory remediation."""

    remediation = _REMEDIATIONS.get(code, "Retry with bounded inputs.")
    action: dict[str, Any] = {"auto_fix": False, "remediation": remediation}
    if extra_action is not None:
        for key, value in extra_action.items():
            if key == "auto_fix":
                action["auto_fix"] = False
            else:
                action[key] = value
    return VoiceError(message, code=code, suggested_action=action)
