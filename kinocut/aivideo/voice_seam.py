"""EOF-clamped voice-seam metrics and aggregate report (Wave 4.2 PR 4.2).

Composes the canonical ASR EOF clamp (:func:`clamp_segments_to_eof`) with
deterministic style metrics, capability-gated speaker-identity providers, and a
public-safe :class:`AudioSeamReport`. No raw transcript, PII, or host paths
leave this module — the report carries only bounded codes, content hashes,
counts, durations, and unit-carrying measurements.

Public surface (controller joins later):

* :func:`analyze_voice_seam` — single-asset analyzer returning an
  :class:`AudioSeamReport`; clamps ASR to EOF before any metric.
* :class:`SpeakerIdentityProvider` — pluggable provider Protocol; when absent,
  the report records ``capability_unavailable`` and never fakes an identity.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Any, Protocol

from pydantic import Field, field_validator

from kinocut.engine_body_swap import _audio_fingerprint
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_command, _validate_input_path
from kinocut.limits import QUALITY_GUARDRAILS_TIMEOUT
from kinocut.subtitles_eof import ClampedSegment, clamp_segments_to_eof

logger = logging.getLogger(__name__)

#: Stable analyzer version prefix; the controller joins reports by this tag.
ANALYZER_VERSION = "kinocut.voice_seam.v1"

#: Default provider id recorded when no speaker-identity provider was supplied.
_NO_PROVIDER_ID = "kinocut.voice_seam.none"

#: Stable error code surfaced when the clamp rejects malformed ASR input.
_INVALID_CLAMP = "invalid_eof_clamp"

#: Privacy-safe provider identity used when a provider exposes an invalid id.
_FAILED_PROVIDER_ID = "kinocut.voice_seam.provider_failed"

# Deterministic metric bounds (no ML; calibrated for explainer-length voice beds).
DEFAULT_PACE_MIN_WPM = 60.0
DEFAULT_PACE_MAX_WPM = 240.0
DEFAULT_CADENCE_MIN_SPM = 5.0
DEFAULT_CADENCE_MAX_SPM = 60.0
DEFAULT_LOUDNESS_MIN_LUFS = -23.0
DEFAULT_LOUDNESS_MAX_LUFS = -10.0
DEFAULT_SILENCE_SEAM_SECONDS = 1.5
DEFAULT_IDENTITY_THRESHOLD = 0.75

# Bounded-code regex (lowercase, dots, underscores, digits — no PII / paths).
_CODE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class VoiceSeamFindingCode(StrEnum):
    """Closed set of deterministic voice-seam finding codes (no raw prose)."""

    PACE_OUTLIER = "pace_outlier"
    CADENCE_OUTLIER = "cadence_outlier"
    SILENCE_SEAM = "silence_seam"
    LOUDNESS_SEAM = "loudness_seam"
    VOICE_IDENTITY_MISMATCH = "voice_identity_mismatch"
    PITCH_PROXY_UNAVAILABLE = "pitch_proxy_unavailable"
    SPEAKER_PROVIDER_FAILED = "speaker_provider_failed"
    TRANSCRIPT_EMPTY = "transcript_empty"


class VoiceSeamSeverity(StrEnum):
    """Bounded severity ladder for a voice-seam finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SpeakerIdentityAvailability(StrEnum):
    """Closed availability state of the speaker-identity resolution."""

    IDENTIFIED = "identified"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    PROVIDER_FAILED = "provider_failed"


# --------------------------------------------------------------------------- #
# Value objects (immutable, unknown-field-rejecting, public-safe)
# --------------------------------------------------------------------------- #


from kinocut.contracts._common import ValueObject  # noqa: E402 — local import keeps top clean


class VoiceSeamMetric(ValueObject):
    """A single named, unit-carrying voice-style measurement."""

    name: str
    value: float
    unit: str

    @field_validator("name", "unit")
    @classmethod
    def _bounded_token(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError("metric name/unit must be 1..64 chars")
        return value


class VoiceSeamFinding(ValueObject):
    """A bounded finding with a closed code, severity, and time range."""

    code: VoiceSeamFindingCode
    severity: VoiceSeamSeverity
    detector: str
    time_range: tuple[float, float]
    measurements: tuple[VoiceSeamMetric, ...] = ()

    @field_validator("detector")
    @classmethod
    def _bounded_detector(cls, value: str) -> str:
        if not value.startswith("kinocut.voice_seam."):
            raise ValueError("detector must be namespaced under kinocut.voice_seam")
        return value

    @field_validator("time_range")
    @classmethod
    def _ordered_nonnegative_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        start, end = value
        if start < 0.0 or end < start:
            raise ValueError("time_range must be a non-negative, ordered pair")
        return value


class TranscriptTimingSummary(ValueObject):
    """Aggregate transcript timing — counts and durations only, no transcript."""

    segment_count: int = Field(ge=0)
    total_speech_seconds: float = Field(ge=0.0)
    words_per_minute: float | None = Field(default=None, ge=0.0)
    clamp_warnings: int = Field(ge=0)
    segments_clamped: int = Field(ge=0)
    segments_dropped: int = Field(ge=0)


class LoudnessSummary(ValueObject):
    """Loudness metrics from the canonical loudnorm analysis (or marked absent)."""

    integrated_lufs: float | None = None
    loudness_range: float | None = None
    true_peak_dbtp: float | None = None
    analysis_available: bool


class VoiceStyleReport(ValueObject):
    """Composed deterministic voice-style metrics and bounded findings."""

    metrics: tuple[VoiceSeamMetric, ...]
    findings: tuple[VoiceSeamFinding, ...]
    transcript_timing: TranscriptTimingSummary


class SpeakerIdentityResult(ValueObject):
    """Capability-gated speaker-identity resolution (never fakes an identity)."""

    provider_id: str
    availability: SpeakerIdentityAvailability
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    reference_label: str | None = None
    reason_code: str | None = None

    @field_validator("provider_id")
    @classmethod
    def _bounded_provider(cls, value: str) -> str:
        if not _CODE_RE.match(value):
            raise ValueError("provider_id must be a bounded lowercase code")
        return value

    @field_validator("reference_label", "reason_code")
    @classmethod
    def _bounded_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _CODE_RE.match(value):
            raise ValueError("reference_label/reason_code must be a bounded lowercase code")
        return value

    @field_validator("similarity_score")
    @classmethod
    def _reject_nan_similarity(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("similarity_score must be finite")
        return value


class AudioSeamReport(ValueObject):
    """Public-safe composed report — no raw transcript, PII, or host paths."""

    audio_fingerprint: str
    transcript_timing: TranscriptTimingSummary
    voice_style: VoiceStyleReport
    loudness: LoudnessSummary
    speaker_identity: SpeakerIdentityResult
    findings: tuple[VoiceSeamFinding, ...]
    analyzer_version: str

    @field_validator("audio_fingerprint")
    @classmethod
    def _fingerprint_is_sha256(cls, value: str) -> str:
        # Allow canonical content hashes and module-owned no-audio sentinels.
        if not re.fullmatch(
            r"sha256:[0-9a-f]{64}|sha256:[0-9a-f]+\.[a-z0-9_.-]+\.v\d+", value
        ) and not value.startswith("sha256:"):
            raise ValueError("audio_fingerprint must be sha256-prefixed")
        return value

    @field_validator("analyzer_version")
    @classmethod
    def _namespaced_version(cls, value: str) -> str:
        if not value.startswith("kinocut.voice_seam."):
            raise ValueError("analyzer_version must be namespaced under kinocut.voice_seam")
        return value


# --------------------------------------------------------------------------- #
# Pluggable speaker-identity provider Protocol
# --------------------------------------------------------------------------- #


class SpeakerIdentityProvider(Protocol):
    """Optional speaker-identity provider — never fakes an identity.

    Implementations MUST return a :class:`SpeakerIdentityResult`. Raising is
    permitted; the analyzer records ``provider_failed`` and continues.
    """

    provider_id: str

    def identify(self, audio_path: str) -> SpeakerIdentityResult:  # pragma: no cover - Protocol
        ...


# --------------------------------------------------------------------------- #
# Internal helpers (each under 80 lines; no duplicated subprocess/fingerprint)
# --------------------------------------------------------------------------- #


def _clamp_error(message: str) -> MCPVideoError:
    """Wrap the canonical clamp error code; never echoes the raw segment."""
    return MCPVideoError(message, error_type="validation_error", code=_INVALID_CLAMP)


def _parameter_error(name: str) -> MCPVideoError:
    """Return one stable, public-safe voice-seam parameter error."""

    return MCPVideoError(
        f"{name} is invalid",
        error_type="validation_error",
        code="invalid_voice_seam_parameter",
    )


def _finite_parameter(value: object, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    """Return a finite real parameter inside optional inclusive bounds."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _parameter_error(name)
    number = float(value)
    if not math.isfinite(number):
        raise _parameter_error(name)
    if minimum is not None and number < minimum:
        raise _parameter_error(name)
    if maximum is not None and number > maximum:
        raise _parameter_error(name)
    return number


def _ordered_bounds(value: object, name: str, *, minimum: float | None = None) -> None:
    """Require a finite two-number interval ordered from low to high."""

    if not isinstance(value, tuple) or len(value) != 2:
        raise _parameter_error(name)
    low = _finite_parameter(value[0], name, minimum=minimum)
    high = _finite_parameter(value[1], name, minimum=minimum)
    if low >= high:
        raise _parameter_error(name)


def _validate_analysis_parameters(
    identity_threshold: object,
    pace_bounds: object,
    cadence_bounds: object,
    loudness_bounds: object,
    silence_seam_seconds: object,
) -> None:
    """Fail closed before any analyzer consumes caller-controlled thresholds."""

    _finite_parameter(identity_threshold, "identity_threshold", minimum=0.0, maximum=1.0)
    _ordered_bounds(pace_bounds, "pace_bounds", minimum=0.0)
    _ordered_bounds(cadence_bounds, "cadence_bounds", minimum=0.0)
    _ordered_bounds(loudness_bounds, "loudness_bounds")
    _finite_parameter(silence_seam_seconds, "silence_seam_seconds", minimum=0.0)


def _validated_audio(audio_path: str) -> str:
    """Resolve and validate the audio path before any analysis step."""

    try:
        return _validate_input_path(audio_path)
    except MCPVideoError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise MCPVideoError(
            "audio path is not readable",
            error_type="input_error",
            code="invalid_input",
        ) from exc


def _word_count(segment: ClampedSegment) -> int:
    """Count whitespace-separated tokens in a clamped segment's text field."""
    text = segment.fields.get("text")
    if not isinstance(text, str):
        return 0
    cleaned = text.strip()
    return len(cleaned.split()) if cleaned else 0


def _transcript_timing(
    segments: Sequence[ClampedSegment],
    clamp_warnings: int,
    clamped: int,
    dropped: int,
) -> TranscriptTimingSummary:
    """Build the public-safe timing summary from clamped segments + clamp counts."""

    total_speech = sum(max(0.0, seg.end - seg.start) for seg in segments)
    words = sum(_word_count(seg) for seg in segments)
    wpm: float | None = None
    if total_speech > 0.0 and words > 0:
        wpm = words / total_speech * 60.0
    return TranscriptTimingSummary(
        segment_count=len(segments),
        total_speech_seconds=total_speech,
        words_per_minute=wpm,
        clamp_warnings=clamp_warnings,
        segments_clamped=clamped,
        segments_dropped=dropped,
    )


def _pace_metric_and_finding(
    timing: TranscriptTimingSummary,
    bounds: tuple[float, float],
) -> tuple[tuple[VoiceSeamMetric, ...], tuple[VoiceSeamFinding, ...]]:
    """Return the pace metric and any outlier finding for it."""

    if timing.words_per_minute is None:
        return (), ()
    metric = VoiceSeamMetric(name="pace_words_per_minute", value=timing.words_per_minute, unit="wpm")
    lo, hi = bounds
    if timing.words_per_minute < lo or timing.words_per_minute > hi:
        severity = (
            VoiceSeamSeverity.HIGH
            if timing.words_per_minute > hi * 1.5 or timing.words_per_minute < lo * 0.5
            else VoiceSeamSeverity.MEDIUM
        )
        finding = VoiceSeamFinding(
            code=VoiceSeamFindingCode.PACE_OUTLIER,
            severity=severity,
            detector=f"{ANALYZER_VERSION}.pace",
            time_range=(0.0, max(0.0, timing.total_speech_seconds)),
            measurements=(metric,),
        )
        return (metric,), (finding,)
    return (metric,), ()


def _cadence_metric_and_finding(
    timing: TranscriptTimingSummary,
    bounds: tuple[float, float],
) -> tuple[tuple[VoiceSeamMetric, ...], tuple[VoiceSeamFinding, ...]]:
    """Return the cadence metric and any outlier finding for it."""

    if timing.total_speech_seconds <= 0.0 or timing.segment_count == 0:
        return (), ()
    spm = timing.segment_count / timing.total_speech_seconds * 60.0
    metric = VoiceSeamMetric(name="cadence_segments_per_minute", value=spm, unit="segments/min")
    lo, hi = bounds
    if spm < lo or spm > hi:
        finding = VoiceSeamFinding(
            code=VoiceSeamFindingCode.CADENCE_OUTLIER,
            severity=VoiceSeamSeverity.MEDIUM,
            detector=f"{ANALYZER_VERSION}.cadence",
            time_range=(0.0, timing.total_speech_seconds),
            measurements=(metric,),
        )
        return (metric,), (finding,)
    return (metric,), ()


def _silence_seam_findings(
    segments: Sequence[ClampedSegment],
    threshold: float,
) -> tuple[VoiceSeamFinding, ...]:
    """Detect gaps > threshold between consecutive clamped ASR segments."""

    if threshold <= 0.0 or len(segments) < 2:
        return ()
    findings: list[VoiceSeamFinding] = []
    for previous, current in pairwise(segments):
        gap = current.start - previous.end
        if gap > threshold:
            findings.append(
                VoiceSeamFinding(
                    code=VoiceSeamFindingCode.SILENCE_SEAM,
                    severity=VoiceSeamSeverity.LOW,
                    detector=f"{ANALYZER_VERSION}.silence",
                    time_range=(previous.end, current.start),
                    measurements=(VoiceSeamMetric(name="silence_gap_seconds", value=gap, unit="s"),),
                )
            )
    return tuple(findings)


def _pitch_proxy_unavailable_finding() -> VoiceSeamFinding:
    """Record that no pitch/prosody provider is configured (honest, never faked)."""

    return VoiceSeamFinding(
        code=VoiceSeamFindingCode.PITCH_PROXY_UNAVAILABLE,
        severity=VoiceSeamSeverity.LOW,
        detector=f"{ANALYZER_VERSION}.pitch_proxy",
        time_range=(0.0, 0.0),
    )


def _voice_style_report(
    segments: Sequence[ClampedSegment],
    timing: TranscriptTimingSummary,
    pace_bounds: tuple[float, float],
    cadence_bounds: tuple[float, float],
    silence_seam_seconds: float,
) -> VoiceStyleReport:
    """Compose deterministic metrics + findings from clamped ASR segments."""

    pace_metrics, pace_findings = _pace_metric_and_finding(timing, pace_bounds)
    cadence_metrics, cadence_findings = _cadence_metric_and_finding(timing, cadence_bounds)
    silence_findings = _silence_seam_findings(segments, silence_seam_seconds)
    pitch_finding = (_pitch_proxy_unavailable_finding(),)
    findings = (*pace_findings, *cadence_findings, *silence_findings, *pitch_finding)
    if timing.segment_count == 0:
        findings = (
            VoiceSeamFinding(
                code=VoiceSeamFindingCode.TRANSCRIPT_EMPTY,
                severity=VoiceSeamSeverity.MEDIUM,
                detector=f"{ANALYZER_VERSION}.transcript",
                time_range=(0.0, 0.0),
            ),
            *findings,
        )
    metrics = (*pace_metrics, *cadence_metrics)
    return VoiceStyleReport(metrics=metrics, findings=findings, transcript_timing=timing)


def _loudness_summary(audio_path: str) -> LoudnessSummary:
    """Run loudnorm via the canonical subprocess wrapper; return a bounded summary.

    Failures (no audio stream, timeout, unparseable JSON) yield
    ``analysis_available=False`` rather than raising — the analyzer continues
    with the rest of the report.
    """

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        audio_path,
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    try:
        result = _run_command(cmd, timeout=QUALITY_GUARDRAILS_TIMEOUT)
    except MCPVideoError:
        logger.warning("voice_seam loudnorm command failed for %s", type(audio_path).__name__)
        return LoudnessSummary(analysis_available=False)
    stderr = result.stderr or ""
    start, end = stderr.find("{"), stderr.rfind("}")
    if start < 0 or end <= start:
        return LoudnessSummary(analysis_available=False)
    try:
        payload = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return LoudnessSummary(analysis_available=False)
    return LoudnessSummary(
        integrated_lufs=_finite_or_none(payload.get("input_i")),
        loudness_range=_finite_or_none(payload.get("input_lra")),
        true_peak_dbtp=_finite_or_none(payload.get("input_tp")),
        analysis_available=True,
    )


def _finite_or_none(value: object) -> float | None:
    """Parse a loudnorm string field into a finite float, or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _loudness_findings(
    loudness: LoudnessSummary,
    bounds: tuple[float, float],
) -> tuple[VoiceSeamFinding, ...]:
    """Flag a loudness seam when integrated LUFS falls outside the bounds."""

    if not loudness.analysis_available or loudness.integrated_lufs is None:
        return ()
    lo, hi = bounds
    value = loudness.integrated_lufs
    if value < lo or value > hi:
        metric = VoiceSeamMetric(name="integrated_lufs", value=value, unit="LUFS")
        return (
            VoiceSeamFinding(
                code=VoiceSeamFindingCode.LOUDNESS_SEAM,
                severity=VoiceSeamSeverity.HIGH,
                detector=f"{ANALYZER_VERSION}.loudness",
                time_range=(0.0, 0.0),
                measurements=(metric,),
            ),
        )
    return ()


def _capability_unavailable_identity() -> SpeakerIdentityResult:
    """The honest result when no speaker-identity provider was configured."""
    return SpeakerIdentityResult(
        provider_id=_NO_PROVIDER_ID,
        availability=SpeakerIdentityAvailability.CAPABILITY_UNAVAILABLE,
        reason_code="no_speaker_provider_configured",
    )


def _resolve_speaker_identity(
    audio_path: str,
    provider: SpeakerIdentityProvider | None,
) -> SpeakerIdentityResult:
    """Call the provider; on absence or failure, return a typed soft-fail result."""

    if provider is None:
        return _capability_unavailable_identity()
    provider_id = _safe_provider_id(provider)
    try:
        result = provider.identify(audio_path)
    except Exception as exc:  # provider boundary; fail soft
        logger.warning(
            "speaker identity provider %s raised: %s",
            provider_id,
            type(exc).__name__,
        )
        return SpeakerIdentityResult(
            provider_id=provider_id,
            availability=SpeakerIdentityAvailability.PROVIDER_FAILED,
            reason_code="provider_raised_exception",
        )
    if type(result) is not SpeakerIdentityResult:
        return SpeakerIdentityResult(
            provider_id=provider_id,
            availability=SpeakerIdentityAvailability.PROVIDER_FAILED,
            reason_code="provider_returned_wrong_type",
        )
    try:
        validated = SpeakerIdentityResult.model_validate(result.model_dump(mode="python"))
    except Exception as exc:
        logger.warning(
            "speaker identity provider %s returned invalid data: %s",
            provider_id,
            type(exc).__name__,
        )
        return SpeakerIdentityResult(
            provider_id=provider_id,
            availability=SpeakerIdentityAvailability.PROVIDER_FAILED,
            reason_code="provider_returned_invalid_result",
        )
    if validated.provider_id != provider_id:
        logger.warning("speaker identity provider returned a mismatched provider id")
        return SpeakerIdentityResult(
            provider_id=provider_id,
            availability=SpeakerIdentityAvailability.PROVIDER_FAILED,
            reason_code="provider_returned_invalid_result",
        )
    return validated


def _safe_provider_id(provider: object) -> str:
    """Return a bounded provider code without leaking hostile metadata."""

    try:
        value = getattr(provider, "provider_id", None)
    except Exception as exc:
        logger.warning("speaker identity provider metadata raised: %s", type(exc).__name__)
        return _FAILED_PROVIDER_ID
    return value if isinstance(value, str) and _CODE_RE.fullmatch(value) else _FAILED_PROVIDER_ID


def _identity_findings(
    identity: SpeakerIdentityResult,
    threshold: float,
) -> tuple[VoiceSeamFinding, ...]:
    """Flag a voice-identity mismatch when similarity falls below the threshold."""

    if identity.availability is not SpeakerIdentityAvailability.IDENTIFIED:
        if identity.availability is SpeakerIdentityAvailability.PROVIDER_FAILED:
            return (
                VoiceSeamFinding(
                    code=VoiceSeamFindingCode.SPEAKER_PROVIDER_FAILED,
                    severity=VoiceSeamSeverity.MEDIUM,
                    detector=f"{ANALYZER_VERSION}.speaker",
                    time_range=(0.0, 0.0),
                ),
            )
        return ()
    score = identity.similarity_score
    if score is None or score < threshold:
        measurements: tuple[VoiceSeamMetric, ...] = ()
        if score is not None:
            measurements = (VoiceSeamMetric(name="speaker_similarity", value=score, unit="cosine"),)
        return (
            VoiceSeamFinding(
                code=VoiceSeamFindingCode.VOICE_IDENTITY_MISMATCH,
                severity=VoiceSeamSeverity.HIGH,
                detector=f"{ANALYZER_VERSION}.speaker",
                time_range=(0.0, 0.0),
                measurements=measurements,
            ),
        )
    return ()


def _audio_identity(audio_path: str) -> str:
    """Bind the source audio identity via the canonical engine fingerprint.

    Falls back to a stable no-audio sentinel if the asset has no audio stream;
    never raises — identity evidence is a public-safe hash, not a host path.
    """

    try:
        return _audio_fingerprint(audio_path)
    except MCPVideoError:
        return "sha256:kinocut.voice_seam.no-audio.v1"


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def analyze_voice_seam(
    audio_path: str,
    asr_segments: Any,
    eof_seconds: float,
    *,
    speaker_provider: SpeakerIdentityProvider | None = None,
    identity_threshold: float = DEFAULT_IDENTITY_THRESHOLD,
    pace_bounds: tuple[float, float] = (DEFAULT_PACE_MIN_WPM, DEFAULT_PACE_MAX_WPM),
    cadence_bounds: tuple[float, float] = (DEFAULT_CADENCE_MIN_SPM, DEFAULT_CADENCE_MAX_SPM),
    loudness_bounds: tuple[float, float] = (DEFAULT_LOUDNESS_MIN_LUFS, DEFAULT_LOUDNESS_MAX_LUFS),
    silence_seam_seconds: float = DEFAULT_SILENCE_SEAM_SECONDS,
) -> AudioSeamReport:
    """Analyze voice-style continuity for one audio asset.

    ASR segments are clamped to the real EOF *before* any metric is computed;
    a malformed span (negative, non-monotonic, bad container) raises a stable
    ``invalid_eof_clamp`` :class:`MCPVideoError` and no partial report is
    produced. Optional providers fail soft: a missing speaker-identity provider
    yields a typed ``capability_unavailable`` result and never fakes an
    identity.

    The returned :class:`AudioSeamReport` is public-safe — it carries only
    bounded codes, content hashes, counts, durations, and unit-carrying
    measurements; no raw transcript text, PII, or host paths escape.
    """

    _validate_analysis_parameters(
        identity_threshold,
        pace_bounds,
        cadence_bounds,
        loudness_bounds,
        silence_seam_seconds,
    )
    validated = _validated_audio(audio_path)

    # 1. Canonical EOF clamp BEFORE any derived metric (single source of truth).
    try:
        clamp_result = clamp_segments_to_eof(asr_segments, eof_seconds)
    except MCPVideoError as exc:
        if exc.code != _INVALID_CLAMP:
            raise
        raise _clamp_error(str(exc)) from exc

    segments = clamp_result.segments
    timing = _transcript_timing(segments, len(clamp_result.warnings), clamp_result.clamped, clamp_result.dropped)

    style = _voice_style_report(segments, timing, pace_bounds, cadence_bounds, silence_seam_seconds)
    loudness = _loudness_summary(validated)
    loudness_findings = _loudness_findings(loudness, loudness_bounds)

    identity = _resolve_speaker_identity(validated, speaker_provider)
    identity_findings = _identity_findings(identity, identity_threshold)

    findings = (*style.findings, *loudness_findings, *identity_findings)
    return AudioSeamReport(
        audio_fingerprint=_audio_identity(validated),
        transcript_timing=timing,
        voice_style=style,
        loudness=loudness,
        speaker_identity=identity,
        findings=findings,
        analyzer_version=ANALYZER_VERSION,
    )
