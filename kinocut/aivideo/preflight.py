"""Unified media preflight report (Plan 01 Task 6).

One typed :class:`PreflightReport` composed over the *shipped* inspection
engines — no parallel probing stack:

* technical metadata (streams, codecs, display dimensions, fps, rotation,
  duration) from :func:`kinocut.engine_probe.probe` and ``_run_ffprobe_json``;
* loudness (integrated LUFS + true peak) from
  :meth:`VisualQualityGuardrails._analyze_loudnorm`, with missing audio stated
  explicitly (``has_audio=False``) rather than reported as a zero-loudness lie;
* color means from :meth:`VisualQualityGuardrails.check_color_balance`;
* full-decode integrity from a single ``ffmpeg -f null`` pass.

The report is serialized to a deterministic, content-addressed, **private**
artifact inside the project store, and the owning :class:`AssetRecord` is
enriched by an append-only *superseding* record that references the artifact —
the original record and the original media bytes are never mutated. Every
malformed-probe or decode failure surfaces as a stable, privacy-safe
:class:`~kinocut.errors.MCPVideoError` that echoes no host path and no raw
FFmpeg stderr.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import PurePosixPath
from typing import Any

from pydantic import Field

from kinocut.contracts._common import ValueObject
from kinocut.contracts.asset import AssetRecord
from kinocut.engine_probe import probe
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import (
    _run_ffmpeg,
    _run_ffprobe_json,
    _validate_input_path,
)
from kinocut.projectstore import Project, layout, store
from kinocut.quality_guardrails import VisualQualityGuardrails

logger = logging.getLogger(__name__)

# A probe/decode failure must never surface a host path or raw ffmpeg stderr.
_PROBE_FAILED = "media preflight could not probe the input"
_DECODE_FAILED = "media failed the full-decode integrity check"
_INPUT_FAILED = "media preflight could not validate the input"


def _probe_failed(exc: Exception) -> MCPVideoError:
    """Collapse any probe-side failure into one stable, privacy-safe error.

    The originating exception (raw ``ValueError``/``RuntimeError``, an unexpected
    marker value, a host path, or FFmpeg stderr) is logged for diagnostics but
    never echoed across the boundary — only the fixed ``_PROBE_FAILED`` message
    and the stable ``preflight_probe_failed`` code escape.
    """

    logger.warning("preflight probe failed: %s", type(exc).__name__)
    return MCPVideoError(_PROBE_FAILED, error_type="input_error", code="preflight_probe_failed")


class StreamInfo(ValueObject):
    """One container stream's identity — index, kind, and codec name."""

    index: int = Field(ge=0)
    codec_type: str
    codec_name: str


class TechnicalInfo(ValueObject):
    """Container/stream technical metadata read straight off the probe."""

    streams: tuple[StreamInfo, ...]
    video_codec: str
    audio_codec: str | None = None
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    fps: float = Field(ge=0.0)
    rotation: int
    duration: float = Field(ge=0.0)


class LoudnessInfo(ValueObject):
    """Loudness posture; measurements are ``None`` — never zero — without audio."""

    has_audio: bool
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None


class ColorInfo(ValueObject):
    """Mean RGB balance; ``analyzed`` is ``False`` if signalstats was unavailable."""

    analyzed: bool
    r_mean: float | None = None
    g_mean: float | None = None
    b_mean: float | None = None
    color_cast: tuple[str, ...] = ()


class IntegrityInfo(ValueObject):
    """Full-decode integrity: whether every frame decoded, and the error count."""

    fully_decoded: bool
    decode_error_count: int = Field(ge=0)


class PreflightReport(ValueObject):
    """The one composed inspection report for a single media asset."""

    technical: TechnicalInfo
    loudness: LoudnessInfo
    color: ColorInfo
    integrity: IntegrityInfo


def _technical(path: str) -> TechnicalInfo:
    """Compose technical metadata, mapping any probe failure to a private error."""

    # The whole assembly — probe, raw-stream parse, and model construction — is
    # inside the boundary: a malformed stream index (raw ``ValueError``) or an
    # unexpected raw ``RuntimeError`` from the probe must not escape as anything
    # but the stable typed error.
    try:
        info = probe(path)
        raw = _run_ffprobe_json(path)
        streams = tuple(
            StreamInfo(
                index=int(s.get("index", 0)),
                codec_type=str(s.get("codec_type", "unknown")),
                codec_name=str(s.get("codec_name", "unknown")),
            )
            for s in raw.get("streams", [])
        )
        return TechnicalInfo(
            streams=streams,
            video_codec=info.codec,
            audio_codec=info.audio_codec,
            # Display dimensions honor the rotation side-datum; coded width/height
            # would report a rotated portrait clip as landscape.
            width=info.display_width,
            height=info.display_height,
            fps=info.fps,
            rotation=info.normalized_rotation,
            duration=info.duration,
        )
    except Exception as exc:
        # Every probe shape — typed, raw ValueError, raw RuntimeError — collapses
        # to one logged, privacy-safe typed error (see _probe_failed).
        raise _probe_failed(exc) from exc


def _to_float(value: Any) -> float | None:
    """Parse a loudnorm numeric field, returning ``None`` on any bad value."""

    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _loudness(guard: VisualQualityGuardrails, path: str) -> LoudnessInfo:
    """Read integrated LUFS + true peak; absent audio yields explicit ``None``s."""

    has_audio = guard._has_audio_stream(path)
    if has_audio is None:
        # Indeterminate probe failure — NOT confirmed-absent audio. Surfacing
        # this as ``has_audio=False`` would be a lie about the media.
        raise _probe_failed(RuntimeError("audio-stream probe was indeterminate"))
    if has_audio is False:
        return LoudnessInfo(has_audio=False)
    data = guard._analyze_loudnorm(path)
    if not data or data.get("_error"):
        # Audio exists but the measurement failed — do not fabricate a value.
        return LoudnessInfo(has_audio=True)
    return LoudnessInfo(
        has_audio=True,
        integrated_lufs=_to_float(data.get("input_i")),
        true_peak_dbtp=_to_float(data.get("input_tp")),
    )


def _color(guard: VisualQualityGuardrails, path: str) -> ColorInfo:
    """Read mean RGB balance from the shipped color-balance guardrail."""

    report = guard.check_color_balance(path)
    details = report.details
    if "r_mean" not in details:
        return ColorInfo(analyzed=False)
    cast = details.get("color_cast") or ()
    return ColorInfo(
        analyzed=True,
        r_mean=_to_float(details.get("r_mean")),
        g_mean=_to_float(details.get("g_mean")),
        b_mean=_to_float(details.get("b_mean")),
        color_cast=tuple(cast),
    )


def _integrity(path: str) -> IntegrityInfo:
    """Full-decode the media; a hard decode failure maps to a private error."""

    try:
        proc = _run_ffmpeg(["-v", "error", "-i", path, "-f", "null", "-"])
    except (InputFileError, ProcessingError) as exc:
        raise MCPVideoError(_DECODE_FAILED, error_type="input_error", code="preflight_decode_failed") from exc
    errors = [line for line in proc.stderr.splitlines() if line.strip()]
    return IntegrityInfo(fully_decoded=not errors, decode_error_count=len(errors))


def build_preflight_report(path: str) -> PreflightReport:
    """Compose the one preflight report for the media at ``path``.

    Technical, loudness, color, and full-decode integrity are read through the
    shipped engines and folded into a single typed report. Missing audio is
    explicit; a malformed probe or decode failure raises a stable, privacy-safe
    :class:`~kinocut.errors.MCPVideoError` with no host path or raw stderr.
    """

    try:
        validated = _validate_input_path(path)
    except Exception as exc:
        logger.warning("preflight input validation failed: %s", type(exc).__name__)
        raise MCPVideoError(_INPUT_FAILED, error_type="input_error", code="preflight_input_failed") from exc
    guard = VisualQualityGuardrails()
    return PreflightReport(
        technical=_technical(validated),
        loudness=_loudness(guard, validated),
        color=_color(guard, validated),
        integrity=_integrity(validated),
    )


def _canonical_artifact(report: PreflightReport) -> tuple[str, str]:
    """Serialize the report canonically and return ``(artifact_id, json_line)``."""

    line = json.dumps(
        report.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    artifact_id = "sha256:" + hashlib.sha256(line.encode("utf-8")).hexdigest()
    return artifact_id, line


def _summary(report: PreflightReport) -> str:
    """A short, path-free one-line summary stored on the enriched record."""

    tech = report.technical
    integrity = "ok" if report.integrity.fully_decoded else "errors"
    return (
        f"{tech.width}x{tech.height} {tech.video_codec} {tech.fps:.2f}fps; "
        f"audio={report.loudness.has_audio}; integrity={integrity}"
    )


def _require_persisted_asset(project: Project, asset: AssetRecord) -> None:
    """Require the caller to exactly match its authoritative stored record."""

    matches = [
        record
        for record in store.read_records(project, "asset_record")
        if isinstance(record, AssetRecord) and record.record_id == asset.record_id
    ]
    if len(matches) != 1 or matches[0] != asset:
        raise MCPVideoError(
            "media preflight asset does not match its persisted record",
            error_type="validation_error",
            code="preflight_asset_mismatch",
        )


def _install_or_verify_artifact(artifact_path: Any, line: str) -> bool:
    """Install canonical bytes once, or verify an identical prior install."""

    expected = line.encode("utf-8")
    try:
        if artifact_path.exists():
            if artifact_path.read_bytes() != expected:
                raise MCPVideoError(
                    "media preflight artifact content does not match its identity",
                    error_type="store_error",
                    code="preflight_artifact_mismatch",
                )
            return False
        store._atomic_write(artifact_path, line)
        return True
    except OSError as exc:
        logger.warning("preflight artifact access failed: %s", type(exc).__name__)
        raise MCPVideoError(
            "media preflight artifact could not be stored",
            error_type="store_error",
            code="preflight_artifact_store_failed",
        ) from exc


def _persist_preflight(project: Project, asset: AssetRecord, report: PreflightReport) -> AssetRecord:
    """Install the report and append its record as one locked transaction."""

    artifact_id, line = _canonical_artifact(report)
    artifact_rel = layout.artifact_relative_path(artifact_id, "preflight.json")
    enriched = asset.model_copy(
        update={
            "record_id": None,
            "supersedes": asset.record_id,
            "preflight_artifact_id": artifact_id,
            "preflight_summary": _summary(report),
        }
    )
    with store._project_lock(project):
        _require_persisted_asset(project, asset)
        artifact_path = store.safe_target(project, artifact_rel)
        artifact_created = _install_or_verify_artifact(artifact_path, line)
        try:
            return store.append_record_locked(project, enriched)
        except Exception as exc:
            logger.warning("preflight record append failed: %s", type(exc).__name__)
            if artifact_created:
                try:
                    artifact_path.unlink(missing_ok=True)
                except Exception as cleanup_exc:
                    logger.warning(
                        "preflight artifact rollback failed: %s",
                        type(cleanup_exc).__name__,
                    )
            raise


def run_preflight(project: Project, asset: AssetRecord) -> AssetRecord:
    """Preflight ``asset``'s stored original and record the result immutably.

    The immutable original is located in the content-addressed store, decoded
    into one :class:`PreflightReport`, and that report is written as a
    deterministic, content-addressed, private artifact. The owning record is then
    enriched by an append-only *superseding* :class:`AssetRecord` that references
    the artifact via ``preflight_artifact_id`` — the prior record and the media
    bytes are never mutated.
    """

    if asset.record_id is None:
        raise MCPVideoError(
            "media preflight requires a persisted asset record",
            error_type="validation_error",
            code="preflight_asset_unpersisted",
        )

    with store._project_lock(project):
        _require_persisted_asset(project, asset)
        media_path = store.safe_target(project, PurePosixPath(asset.original_location))
    report = build_preflight_report(str(media_path))
    return _persist_preflight(project, asset, report)
