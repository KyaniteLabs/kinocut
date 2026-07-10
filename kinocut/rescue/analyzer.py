"""Read-only, bounded source analysis for dedicated rescue plans."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..engine_probe import probe
from ..engine_thumbnail import thumbnail
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffprobe_json
from ..models import VideoInfo
from ..quality_guardrails import QualityReport, VisualQualityGuardrails
from ..workflow.planner import _hash_if_exists
from ._errors import INVALID_RESCUE_INPUT, rescue_error
from .models import (
    Finding,
    Metric,
    PreviewArtifact,
    RepairType,
    RescueEstimate,
    SourceIdentity,
)

_PREVIEW_RATIOS = (0.1, 0.5, 0.9)


@dataclass(frozen=True)
class AnalysisResult:
    """Validated source evidence collected without mutating the input."""

    source: SourceIdentity
    findings: list[Finding]
    previews: list[PreviewArtifact]
    estimate: RescueEstimate
    deferred_analyzers: list[str]
    observed_planning_seconds: float


def _confined_realpath(path: str | Path, workspace_root: Path, label: str) -> Path:
    resolved = Path(os.path.realpath(path))
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise rescue_error(
            f"{label} must be inside the rescue workspace",
            INVALID_RESCUE_INPUT,
        ) from exc
    return resolved


def _metric(
    name: str,
    value: float | int | str | bool | None,
    unit: str,
    definition: str,
    *,
    available: bool = True,
) -> Metric:
    return Metric(
        name=name,
        value=value,
        unit=unit,
        definition=definition,
        available=available,
    )


def _unavailable_finding(
    finding_id: str,
    repair_type: RepairType,
    report: QualityReport,
    metric_name: str,
    unit: str,
    definition: str,
) -> Finding:
    return Finding(
        id=finding_id,
        type=repair_type,
        summary=report.message,
        evidence=[_metric(metric_name, None, unit, definition, available=False)],
        confidence=0.0,
        confidence_rationale="The local analyzer did not return a usable measurement.",
        expected_benefit="Record the missing measurement without inventing a value.",
        tradeoffs=[],
        executor=None,
        available=False,
        contraindications=["No repair may execute without a valid measurement."],
    )


def _rotation_findings(info: VideoInfo) -> list[Finding]:
    if info.rotation not in {90, 180, 270, -90, -180, -270}:
        return []
    return [
        Finding(
            id="rotation:display-matrix",
            type=RepairType.ROTATION,
            summary=f"The video declares a {info.rotation}-degree display rotation.",
            evidence=[
                _metric(
                    "display_rotation",
                    info.rotation,
                    "degrees",
                    "Clockwise display rotation declared by the primary video stream.",
                )
            ],
            confidence=1.0,
            confidence_rationale="The value comes directly from ffprobe stream side data.",
            parameters={"angle": info.rotation % 360},
            expected_benefit="Preserve the intended viewing orientation in derived outputs.",
            tradeoffs=["Video pixels may be re-encoded when rotation metadata is normalized."],
            executor="ffmpeg.transpose",
        )
    ]


def _audio_findings(report: QualityReport, has_audio: bool) -> list[Finding]:
    if not has_audio or report.passed:
        return []
    lufs = report.details.get("lufs")
    true_peak = report.details.get("true_peak")
    if lufs is None or true_peak is None:
        return [
            _unavailable_finding(
                "audio_loudness:primary",
                RepairType.AUDIO_LOUDNESS,
                report,
                "integrated_loudness",
                "LUFS",
                "Integrated program loudness measured over the complete audio stream.",
            )
        ]
    return [
        Finding(
            id="audio_loudness:primary",
            type=RepairType.AUDIO_LOUDNESS,
            summary=report.message,
            evidence=[
                _metric(
                    "integrated_loudness",
                    float(lufs),
                    "LUFS",
                    "Integrated program loudness measured over the complete audio stream.",
                ),
                _metric(
                    "true_peak",
                    float(true_peak),
                    "dBTP",
                    "Maximum reconstructed audio peak relative to digital full scale.",
                ),
            ],
            confidence=0.98,
            confidence_rationale="FFmpeg loudnorm measured the complete audio stream.",
            parameters={"target_lufs": -16.0, "lra": 11.0},
            expected_benefit="Make speech consistently audible without digital clipping.",
            tradeoffs=["Audio is re-encoded."],
            executor="ffmpeg.loudnorm",
        )
    ]


def _exposure_findings(report: QualityReport) -> list[Finding]:
    if report.passed:
        return []
    y_avg = report.details.get("y_avg")
    if y_avg is None:
        return [
            _unavailable_finding(
                "exposure:primary",
                RepairType.EXPOSURE,
                report,
                "mean_luma",
                "8bit_luma",
                "Mean Y-channel value across analyzed video frames on the 0-255 scale.",
            )
        ]
    return [
        Finding(
            id="exposure:primary",
            type=RepairType.EXPOSURE,
            summary=report.message,
            evidence=[
                _metric(
                    "mean_luma",
                    float(y_avg),
                    "8bit_luma",
                    "Mean Y-channel value across analyzed video frames on the 0-255 scale.",
                )
            ],
            confidence=0.9,
            confidence_rationale="FFmpeg signalstats measured luma across the source.",
            parameters={"level": max(-0.08, min(0.08, (128.0 - float(y_avg)) / 255.0))},
            expected_benefit="Bring facial detail into a broadly viewable luminance range.",
            tradeoffs=["Strong correction can reveal noise or compress highlights."],
            executor="ffmpeg.eq",
        )
    ]


def _white_balance_findings(report: QualityReport) -> list[Finding]:
    if report.passed:
        return []
    deviation = report.details.get("max_deviation")
    if deviation is None:
        return [
            _unavailable_finding(
                "white_balance:primary",
                RepairType.WHITE_BALANCE,
                report,
                "rgb_channel_deviation",
                "percent",
                "Maximum mean RGB-channel deviation from the three-channel average.",
            )
        ]
    return [
        Finding(
            id="white_balance:primary",
            type=RepairType.WHITE_BALANCE,
            summary=report.message,
            evidence=[
                _metric(
                    "rgb_channel_deviation",
                    float(deviation),
                    "percent",
                    "Maximum mean RGB-channel deviation from the three-channel average.",
                )
            ],
            confidence=0.75,
            confidence_rationale="The estimate derives from FFmpeg YUV means converted to approximate RGB means.",
            parameters={"maximum_channel_deviation_percent": float(deviation)},
            expected_benefit="Reduce a measured global color cast.",
            tradeoffs=["A global correction may not suit mixed lighting."],
            executor="ffmpeg.colorbalance",
            contraindications=["Mixed lighting or intentional color treatment requires human review."],
        )
    ]


def _stability_findings(raw: dict[str, Any]) -> list[Finding]:
    if not any(stream.get("codec_type") == "video" for stream in raw.get("streams", [])):
        return []
    return [
        Finding(
            id="stabilization:camera-motion",
            type=RepairType.STABILIZATION,
            summary="Automated camera-motion measurement is not available in the bounded local analyzer.",
            evidence=[
                _metric(
                    "camera_motion",
                    None,
                    "pixels_per_frame",
                    "Estimated inter-frame camera displacement after excluding subject motion.",
                    available=False,
                )
            ],
            confidence=0.0,
            confidence_rationale="The source probe does not distinguish camera shake from subject motion.",
            expected_benefit="Make the missing stability evidence explicit for policy and human review.",
            tradeoffs=[],
            executor=None,
            available=False,
            contraindications=["Stabilization must not execute without motion evidence and crop review."],
        )
    ]


def _candidate_findings(
    info: VideoInfo,
    raw: dict[str, Any],
    quality: dict[str, QualityReport],
) -> list[Finding]:
    has_audio = any(stream.get("codec_type") == "audio" for stream in raw.get("streams", []))
    findings = _rotation_findings(info)
    findings.extend(_audio_findings(quality["audio_levels"], has_audio))
    findings.extend(_exposure_findings(quality["brightness"]))
    findings.extend(_white_balance_findings(quality["color_balance"]))
    findings.extend(_stability_findings(raw))
    return findings


def _stream_inventory(raw: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {
        "index",
        "codec_name",
        "codec_type",
        "width",
        "height",
        "pix_fmt",
        "sample_rate",
        "channels",
        "channel_layout",
        "duration",
        "r_frame_rate",
        "avg_frame_rate",
        "time_base",
    }
    return [{key: value for key, value in stream.items() if key in allowed} for stream in raw.get("streams", [])]


def _estimate(info: VideoInfo, findings: list[Finding]) -> RescueEstimate:
    megapixel_seconds = max(info.width * info.height, 1) * max(info.duration, 0.1) / 1_000_000
    executor_cost = sum(0.35 if finding.executor else 0.0 for finding in findings)
    seconds = round(max(1.0, megapixel_seconds * (0.8 + executor_cost)), 3)
    return RescueEstimate(
        seconds=seconds,
        hardware={
            "processor": platform.processor() or "unknown",
            "system": platform.system() or "unknown",
            "cpu_count": os.cpu_count(),
        },
        confidence="medium" if findings else "low",
    )


def analyze_source(
    source_path: str,
    workspace_root: Path,
    preview_dir: Path,
    *,
    sample_limit: int = 120,
) -> AnalysisResult:
    """Validate, measure, and preview one workspace-confined video source."""

    started = time.monotonic()
    if not 1 <= sample_limit <= 120:
        raise rescue_error("sample_limit must be between 1 and 120", INVALID_RESCUE_INPUT)

    root = Path(os.path.realpath(workspace_root))
    if not root.is_dir():
        raise rescue_error("workspace_root must be an existing directory", INVALID_RESCUE_INPUT)
    source = _confined_realpath(source_path, root, "source_path")
    previews_root = _confined_realpath(preview_dir, root, "preview_dir")
    if not source.is_file():
        raise rescue_error("source_path must be a readable regular file", INVALID_RESCUE_INPUT)

    source_hash = _hash_if_exists(source, {})
    if source_hash is None:
        raise rescue_error("source_path could not be hashed", INVALID_RESCUE_INPUT)

    try:
        info = probe(str(source))
        raw = _run_ffprobe_json(str(source))
    except (MCPVideoError, OSError) as exc:
        raise rescue_error("source_path is not a valid video", INVALID_RESCUE_INPUT) from exc
    if not any(stream.get("codec_type") == "video" for stream in raw.get("streams", [])):
        raise rescue_error("source_path has no video stream", INVALID_RESCUE_INPUT)

    guardrails = VisualQualityGuardrails()
    quality = {
        "brightness": guardrails.check_brightness(str(source)),
        "audio_levels": guardrails.check_audio_levels(str(source)),
        "color_balance": guardrails.check_color_balance(str(source)),
    }
    findings = _candidate_findings(info, raw, quality)

    previews_root.mkdir(parents=True, exist_ok=True)
    previews: list[PreviewArtifact] = []
    for ratio in _PREVIEW_RATIOS:
        timestamp = info.duration * ratio
        output = previews_root / f"preview-{int(ratio * 100):02d}.jpg"
        thumbnail(str(source), timestamp=timestamp, output_path=str(output))
        preview_hash = _hash_if_exists(output, {})
        if preview_hash is None:
            raise rescue_error("preview artifact could not be hashed", INVALID_RESCUE_INPUT)
        previews.append(
            PreviewArtifact(
                path=output.relative_to(root).as_posix(),
                timestamp_seconds=timestamp,
                timestamp_ratio=ratio,
                sha256=preview_hash,
            )
        )

    return AnalysisResult(
        source=SourceIdentity(
            path=source.relative_to(root).as_posix(),
            sha256=source_hash,
            size_bytes=source.stat().st_size,
            streams=_stream_inventory(raw),
        ),
        findings=findings,
        previews=previews,
        estimate=_estimate(info, findings),
        deferred_analyzers=["stabilization", "content_semantics"],
        observed_planning_seconds=round(time.monotonic() - started, 6),
    )
