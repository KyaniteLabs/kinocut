"""Audio normalization operation for the FFmpeg engine.

This module implements a two-pass EBU R128 / ITU-R BS.1770-4 ``loudnorm``
flow so the integrated-loudness target, the loudness range, and the
true-peak ceiling are honoured deterministically on every render:

* **Pass one** (``-af loudnorm=I=...:TP=...:LRA=...:print_format=json``)
  emits a JSON summary line to stderr that records what the loudnorm
  filter actually measured on the source material.
* **Pass two** (``loudnorm=...:measured_I=...:measured_TP=...:
  measured_LRA=...:measured_thresh=...:offset=...:linear=true``) feeds
  pass-one measurements back so the second pass can hit the requested
  loudness targets without the noisy first-pass transient behaviour that
  a single-pass ``loudnorm`` exhibits on dynamic speech / music.

Public callers continue to pass ``target_lufs`` and ``lra`` with the same
defaults. A new ``true_peak_dbtp`` argument is configurable; validation
follows the repository's :class:`MCPVideoError` / ``validation_error`` /
``invalid_parameter`` conventions and never relies on shell strings.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .engine_runtime_utils import (
    _build_edit_result,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult

# Bounds documented in the loudnorm filter and EBU R128 recommendations.
_TARGET_LUFS_MIN = -70.0
_TARGET_LUFS_MAX = -5.0
_TARGET_LRA_MIN = 0.0
_TARGET_LRA_MAX = 50.0
_TARGET_TP_MIN = -12.0
_TARGET_TP_MAX = 0.0
_DEFAULT_TRUE_PEAK_DBTP = -1.0

# Audio is re-encoded by the loudnorm filter graph itself, so we keep
# the codec/bitrate request conservative and consistent with the rest
# of the engine.
_AUDIO_BITRATE = "192k"

# Well-known keys the loudnorm filter emits in ``print_format=json``.
_LOUDNORM_JSON_KEYS = (
    "input_i",
    "input_tp",
    "input_lra",
    "input_thresh",
    "output_i",
    "output_tp",
    "output_lra",
    "output_thresh",
    "normalization_type",
    "target_offset",
)


def _action(description: str, recovery: str | None = None) -> dict[str, Any]:
    """Build a uniform ``suggested_action`` dict for MCPVideoError.

    The repository uses ``{"auto_fix": False, "description": "..."}``
    for all MCP-error surfaces; the optional ``recovery`` key is merged
    so callers can surface both a description and a recovery hint in
    the same shape other engine modules emit.
    """

    action: dict[str, Any] = {"auto_fix": False, "description": description}
    if recovery:
        action["recovery"] = recovery
    return action


def _validate_loudnorm_param(
    value: float,
    *,
    name: str,
    min_value: float,
    max_value: float,
) -> float:
    """Validate a single loudnorm numeric parameter.

    Uses the repository's :class:`MCPVideoError` schema so the failure
    surfaces through the same ``validation_error`` channel the rest of
    the engine raises.
    """

    number = _sanitize_ffmpeg_number(value, name)
    if not (min_value <= number <= max_value):
        raise MCPVideoError(
            f"{name} must be between {min_value} and {max_value}, got {number}",
            error_type="validation_error",
            code="invalid_parameter",
            suggested_action=_action(f"Correct the {name} argument and retry."),
        )
    return number


def _escape_loudnorm_number(value: float) -> str:
    """Format a finite loudnorm numeric value for filter-graph embedding.

    Whitespace, quotes, ``=`` and ``:`` are escaped via the existing
    filter-value helper to keep the construction identical to other
    engine filters even though loudnorm only consumes floats.
    """

    return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, "loudnorm number")))


def _parse_loudnorm_measurements(stderr: str) -> dict[str, float]:
    """Extract the loudnorm JSON summary from a pass-one FFmpeg stderr.

    FFmpeg prints ``[Parsed_loudnorm_0 @ ...]`` followed by a single-line
    JSON object once the filter finishes analysing the stream. The
    *last* ``{...}`` block in stderr corresponds to the requested
    ``print_format=json`` emission; any earlier matches belong to
    unrelated filter logs.

    The function raises :class:`MCPVideoError` with a plain-language
    suggested-action so the orchestrator can surface a recovery hint
    instead of a raw ``json.JSONDecodeError`` traceback.
    """

    # Match the last balanced JSON object across the captured stderr.
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}")
    if json_start < 0 or json_end <= json_start:
        tail = stderr[-400:].strip() if stderr else "stderr was empty"
        raise MCPVideoError(
            "loudnorm pass one did not emit a JSON measurement block",
            error_type="processing_error",
            code="loudnorm_measurements_missing",
            suggested_action=_action(tail, "Re-run with a longer input or verify the loudnorm filter is installed."),
        )
    blob = stderr[json_start : json_end + 1]
    # Loudnorm occasionally serialises a trailing comma-free object that
    # contains tiny JSON-1.0-quirks; fall back to a forgiving regex sweep
    # only if the structured parse fails, so real parse errors still
    # propagate as actionable failures.
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError as exc:
        payload = _loose_loudnorm_parse(blob, exc)
    if not isinstance(payload, dict):
        raise MCPVideoError(
            "loudnorm measurement payload was not a JSON object",
            error_type="processing_error",
            code="loudnorm_measurements_invalid",
            suggested_action=_action(
                f"got type {type(payload).__name__}",
                "Inspect the stderr tail and ensure loudnorm ran in JSON mode.",
            ),
        )
    return _coerce_measurements(payload)


_LOUDNORM_KEY_RE = re.compile(r'"(?P<k>[a-z_]+)"\s*:\s*[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')


def _loose_loudnorm_parse(blob: str, original: json.JSONDecodeError) -> dict[str, float]:
    """Fallback numeric sweep when the canonical loudnorm JSON is malformed."""

    matches: dict[str, float] = {}
    for m in _LOUDNORM_KEY_RE.finditer(blob):
        try:
            matches[m.group("k")] = float(m.group(0).split(":", 1)[1])
        except (ValueError, IndexError):
            continue
    if not matches:
        raise MCPVideoError(
            "loudnorm measurement JSON could not be decoded",
            error_type="processing_error",
            code="loudnorm_measurements_malformed",
            suggested_action=_action(
                f"json error: {original.msg} at line {original.lineno} column {original.colno}",
                "Reinstall FFmpeg with a current loudnorm filter and retry.",
            ),
        ) from original
    return matches


def _coerce_measurements(payload: dict[str, object]) -> dict[str, float]:
    """Coerce the loudnorm payload to ``float`` for every well-known key."""

    coerced: dict[str, float] = {}
    for key in _LOUDNORM_JSON_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        try:
            coerced[key] = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    missing = [name for name in required if name not in coerced]
    if missing:
        raise MCPVideoError(
            "loudnorm pass one measurement JSON is missing required keys",
            error_type="processing_error",
            code="loudnorm_measurements_incomplete",
            suggested_action=_action(
                f"missing keys: {missing}",
                "Re-run with print_format=json and ensure loudnorm ran to completion.",
            ),
        )
    return coerced


def _build_loudnorm_pass_one_filter(
    target_lufs: float,
    true_peak_dbtp: float,
    lra: float,
) -> str:
    """Return the pass-one ``-af loudnorm=...`` filter graph string."""

    safe_i = _escape_loudnorm_number(target_lufs)
    safe_tp = _escape_loudnorm_number(true_peak_dbtp)
    safe_lra = _escape_loudnorm_number(lra)
    return f"loudnorm=I={safe_i}:TP={safe_tp}:LRA={safe_lra}:print_format=json"


def _build_loudnorm_pass_two_filter(
    target_lufs: float,
    true_peak_dbtp: float,
    lra: float,
    measurements: dict[str, float],
) -> str:
    """Return the pass-two filter graph seeded with pass-one measurements."""

    safe_i = _escape_loudnorm_number(target_lufs)
    safe_tp = _escape_loudnorm_number(true_peak_dbtp)
    safe_lra = _escape_loudnorm_number(lra)
    safe_mi = _escape_loudnorm_number(measurements["input_i"])
    safe_mtp = _escape_loudnorm_number(measurements["input_tp"])
    safe_mlra = _escape_loudnorm_number(measurements["input_lra"])
    safe_mthresh = _escape_loudnorm_number(measurements["input_thresh"])
    safe_offset = _escape_loudnorm_number(measurements["target_offset"])
    return (
        f"loudnorm=I={safe_i}:TP={safe_tp}:LRA={safe_lra}"
        f":measured_I={safe_mi}:measured_TP={safe_mtp}:measured_LRA={safe_mlra}"
        f":measured_thresh={safe_mthresh}:offset={safe_offset}:linear=true"
        f":print_format=summary"
    )


def normalize_audio(
    input_path: str,
    target_lufs: float = -16.0,
    lra: float = 11.0,
    true_peak_dbtp: float = _DEFAULT_TRUE_PEAK_DBTP,
    output_path: str | None = None,
) -> EditResult:
    """Normalize audio loudness to a target LUFS level using two-pass loudnorm.

    Args:
        input_path: Path to the input video.
        target_lufs: Target integrated loudness in LUFS. Common values:
            -16 (YouTube), -23 (EBU R128/broadcast), -14 (Apple/Spotify).
        lra: Loudness range target in LU. Default 11.0.
        true_peak_dbtp: True-peak ceiling in dBTP that loudnorm must not
            exceed. Default -1.0 dBTP, the broadcast-safe value that
            preserves headroom for downstream codecs and resamplers.
            Range ``-12.0`` to ``0.0``.
        output_path: Where to save the output.
    """
    input_path = _validate_input_path(input_path)
    safe_target_lufs = _validate_loudnorm_param(
        target_lufs, name="target_lufs", min_value=_TARGET_LUFS_MIN, max_value=_TARGET_LUFS_MAX
    )
    safe_lra = _validate_loudnorm_param(lra, name="lra", min_value=_TARGET_LRA_MIN, max_value=_TARGET_LRA_MAX)
    safe_true_peak = _validate_loudnorm_param(
        true_peak_dbtp,
        name="true_peak_dbtp",
        min_value=_TARGET_TP_MIN,
        max_value=_TARGET_TP_MAX,
    )
    _require_filter("loudnorm", "Audio normalization")
    output = output_path or _auto_output(input_path, "normalized")
    _validate_output_path(output)

    pass_one_filter = _build_loudnorm_pass_one_filter(safe_target_lufs, safe_true_peak, safe_lra)

    with _timed_operation() as timing:
        try:
            pass_one = _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_codec="copy",
                    audio_filter=pass_one_filter,
                    audio_bitrate=_AUDIO_BITRATE,
                )
            )
        except MCPVideoError as exc:
            raise MCPVideoError(
                f"loudnorm pass one (measurement) failed: {exc}",
                error_type="processing_error",
                code="loudnorm_pass_one_failed",
                suggested_action=_action("Verify the input stream has a valid audio track and retry."),
            ) from exc

        try:
            measurements = _parse_loudnorm_measurements(pass_one.stderr or "")
        except MCPVideoError as exc:
            # FFmpeg succeeds without invoking loudnorm when the input has no
            # audio stream. Preserve that safe no-op output rather than
            # translating a missing analysis block into an unrelated failure.
            if exc.code != "loudnorm_measurements_missing" or not Path(output).is_file():
                raise
            measurements = None

        # Very short audio can report ``-inf`` integrated loudness. In that
        # case the completed first pass is the only valid loudnorm result;
        # feeding non-finite measurements into pass two is invalid FFmpeg
        # syntax, so retain the first-pass output.
        if measurements is not None and all(math.isfinite(value) for value in measurements.values()):
            pass_two_filter = _build_loudnorm_pass_two_filter(safe_target_lufs, safe_true_peak, safe_lra, measurements)
            try:
                _run_ffmpeg(
                    _build_ffmpeg_cmd(
                        input_path,
                        output_path=output,
                        video_codec="copy",
                        audio_filter=pass_two_filter,
                        audio_bitrate=_AUDIO_BITRATE,
                    )
                )
            except MCPVideoError as exc:
                raise MCPVideoError(
                    f"loudnorm pass two (apply) failed: {exc}",
                    error_type="processing_error",
                    code="loudnorm_pass_two_failed",
                    suggested_action=_action("Inspect the measured values and the pass-two stderr before retrying."),
                ) from exc

    return _build_edit_result(
        output,
        "normalize_audio",
        timing,
        format=Path(output).suffix.lstrip(".") or "wav",
        audio_only=True,
    )
