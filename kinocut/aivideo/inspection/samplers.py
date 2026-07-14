"""Decoded-timestamp sampling and source-resolution temporal crops."""

from __future__ import annotations

import json
import itertools
import logging
import math
import re

from pydantic import field_validator

from kinocut.aivideo.inspection.manifest import (
    ArtifactRef,
    RegionCropArtifactRef,
    TimestampedArtifactRef,
)
from kinocut.contracts._common import NormalizedRegion, ValueObject
from kinocut.defaults import (
    DEFAULT_INSPECTION_IMAGE_QUALITY,
    DEFAULT_INSPECTION_SAMPLE_PERCENTAGES,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import (
    _run_command,
    _run_ffmpeg_bytes,
    _run_ffprobe_json,
    _validate_input_path,
)
from kinocut.limits import FFPROBE_TIMEOUT
from kinocut.projectstore import Project
from kinocut.projectstore.artifacts import install_bytes

logger = logging.getLogger(__name__)
DEFAULT_SAMPLE_PERCENTAGES = DEFAULT_INSPECTION_SAMPLE_PERCENTAGES
_LABELS = (*tuple(str(value) for value in DEFAULT_SAMPLE_PERCENTAGES), "last")
_REGION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class TimestampSample(ValueObject):
    """One real decoded timestamp carrying one or more policy labels."""

    timestamp: float
    labels: tuple[str, ...]

    @field_validator("timestamp")
    @classmethod
    def _timestamp_is_finite_nonnegative(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("timestamp must be finite and nonnegative")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value) or any(item not in _LABELS for item in value):
            raise ValueError("labels must be unique approved sampling labels")
        return value


class DeclaredRegion(ValueObject):
    """A named text/logo region in normalized source coordinates."""

    name: str
    region: NormalizedRegion

    @field_validator("name")
    @classmethod
    def _name_is_bounded(cls, value: str) -> str:
        if _REGION_NAME_RE.fullmatch(value) is None:
            raise ValueError("region name must be a bounded lowercase code")
        return value


def _nearest(decoded: tuple[float, ...], target: float) -> float:
    return min(decoded, key=lambda value: (abs(value - target), value))


def choose_sample_timestamps(decoded: tuple[float, ...]) -> tuple[TimestampSample, ...]:
    """Map the approved policy onto actual decoded timestamps and deduplicate."""

    ordered = tuple(sorted(set(decoded)))
    if not ordered or any(not math.isfinite(value) or value < 0.0 for value in ordered):
        raise MCPVideoError(
            "inspection found no valid decodable video timestamps",
            error_type="input_error",
            code="no_decodable_frames",
        )
    first, last = ordered[0], ordered[-1]
    targets = [first + (last - first) * percent / 100.0 for percent in DEFAULT_SAMPLE_PERCENTAGES]
    selected = [_nearest(ordered, target) for target in targets] + [last]
    grouped: dict[float, list[str]] = {}
    for timestamp, label in zip(selected, _LABELS, strict=True):
        grouped.setdefault(timestamp, []).append(label)
    return tuple(TimestampSample(timestamp=timestamp, labels=tuple(labels)) for timestamp, labels in grouped.items())


def _decoded_timestamps(path: str) -> tuple[float, ...]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "json",
        path,
    ]
    try:
        payload = json.loads(_run_command(cmd, timeout=FFPROBE_TIMEOUT).stdout)
        values = tuple(
            float(frame["best_effort_timestamp_time"])
            for frame in payload.get("frames", ())
            if frame.get("best_effort_timestamp_time") is not None
        )
    except Exception as exc:
        logger.warning("inspection timestamp probe failed: %s", type(exc).__name__)
        raise MCPVideoError(
            "inspection could not read decoded timestamps",
            error_type="input_error",
            code="timestamp_probe_failed",
        ) from exc
    return values


def sample_decoded_timestamps(path: str) -> tuple[TimestampSample, ...]:
    """Return the exact 0/25/50/75/95/last policy on decoded frame truth."""

    try:
        validated = _validate_input_path(path)
    except Exception as exc:
        raise MCPVideoError(
            "inspection could not validate the input",
            error_type="input_error",
            code="inspection_input_failed",
        ) from exc
    return choose_sample_timestamps(_decoded_timestamps(validated))


def _render_frame(input_path: str, timestamp: float, crop: str | None = None) -> bytes:
    args = ["-noautorotate", "-i", input_path, "-ss", f"{timestamp:.9f}"]
    if crop is not None:
        args.extend(["-vf", crop])
    args.extend(
        [
            "-frames:v",
            "1",
            "-q:v",
            str(DEFAULT_INSPECTION_IMAGE_QUALITY),
            "-threads",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
    )
    return _run_ffmpeg_bytes(args)


def _install_frame(project: Project, input_path: str, sample: TimestampSample, index: int) -> TimestampedArtifactRef:
    rendered = _render_frame(input_path, sample.timestamp)
    installed = install_bytes(project, rendered, name=f"frame_{index:02d}.jpg")
    return TimestampedArtifactRef(
        artifact=ArtifactRef(
            artifact_id=installed.artifact_id,
            kind="sampled_frame",
            location=installed.location,
        ),
        timestamp=sample.timestamp,
        labels=sample.labels,
    )


def extract_sampled_frames(
    project: Project, path: str, samples: tuple[TimestampSample, ...]
) -> tuple[TimestampedArtifactRef, ...]:
    """Extract each sample through real FFmpeg and install it canonically."""

    validated = _validate_input_path(path)
    return tuple(_install_frame(project, validated, sample, index) for index, sample in enumerate(samples))


def _source_dimensions(path: str) -> tuple[int, int]:
    try:
        raw = _run_ffprobe_json(path)
        video = next(
            (stream for stream in raw.get("streams", ()) if stream.get("codec_type") == "video"),
            None,
        )
        if video is None:
            raise KeyError("video stream")
        dimensions = int(video["width"]), int(video["height"])
        if dimensions[0] <= 0 or dimensions[1] <= 0:
            raise ValueError("nonpositive dimensions")
        return dimensions
    except Exception as exc:
        logger.warning("inspection source-dimension probe failed: %s", type(exc).__name__)
        raise MCPVideoError(
            "inspection could not read source dimensions",
            error_type="input_error",
            code="source_dimensions_failed",
        ) from exc


def _pixel_crop(region: NormalizedRegion, width: int, height: int) -> str:
    left = math.floor(region.x * width)
    top = math.floor(region.y * height)
    right = math.ceil((region.x + region.width) * width)
    bottom = math.ceil((region.y + region.height) * height)
    return f"crop={right - left}:{bottom - top}:{left}:{top}"


def _install_crop(
    project: Project,
    input_path: str,
    sample: TimestampSample,
    declared: DeclaredRegion,
    dimensions: tuple[int, int],
    index: int,
) -> RegionCropArtifactRef:
    rendered = _render_frame(
        input_path,
        sample.timestamp,
        _pixel_crop(declared.region, *dimensions),
    )
    installed = install_bytes(project, rendered, name=f"crop_{declared.name}_{index:02d}.jpg")
    return RegionCropArtifactRef(
        artifact=ArtifactRef(
            artifact_id=installed.artifact_id,
            kind="region_crop",
            location=installed.location,
        ),
        timestamp=sample.timestamp,
        name=declared.name,
        region=declared.region,
    )


def extract_region_crops(
    project: Project,
    path: str,
    samples: tuple[TimestampSample, ...],
    regions: tuple[DeclaredRegion, ...],
) -> tuple[RegionCropArtifactRef, ...]:
    """Extract normalized regions at source resolution for every sample."""

    validated = _validate_input_path(path)
    dimensions = _source_dimensions(validated)
    return tuple(
        _install_crop(project, validated, sample, region, dimensions, index)
        for index, (sample, region) in enumerate(itertools.product(samples, regions))
    )
