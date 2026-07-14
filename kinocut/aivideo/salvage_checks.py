"""Independent descriptor-backed preservation checks for salvage recipes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from kinocut.aivideo.salvage_render import _crop_filter, _probe_source
from kinocut.contracts._common import ValueObject
from kinocut.defaults import (
    DEFAULT_CRF,
    DEFAULT_PRESET,
    DEFAULT_SALVAGE_DURATION_TOLERANCE_SECONDS,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _run_command,
    _run_ffmpeg,
)


class PreservationCheck(ValueObject):
    claim: str
    passed: bool
    expected: str
    observed: str


def _salvage_error(message: str, code: str) -> MCPVideoError:
    error_type = {
        "salvage_integrity_failed": "integrity_error",
        "salvage_verification_failed": "processing_error",
    }.get(code, "validation_error")
    return MCPVideoError(message, error_type=error_type, code=code)


def _parse_frame_hashes(stdout: str) -> tuple[str, ...]:
    values = tuple(
        "md5:" + line.rsplit(",", 1)[1].strip().lower()
        for line in stdout.splitlines()
        if line and not line.startswith("#") and "," in line
    )
    if not values or any(
        len(value) != 36 or any(char not in "0123456789abcdef" for char in value[4:]) for value in values
    ):
        raise _salvage_error("decoded frame hash is unavailable", "salvage_verification_failed")
    return values


def _decoded_frame_hashes(path: Path, *, pass_fds: tuple[int, ...] = ()) -> tuple[str, ...]:
    """Return ordered hashes for every decoded video frame."""

    result = _run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-f",
            "framemd5",
            "-",
        ],
        pass_fds=pass_fds,
    )
    return _parse_frame_hashes(result.stdout)


def _decoded_frame_hash_at(
    path: Path,
    timestamp: float,
    video_filter: str | None = None,
    *,
    pass_fds: tuple[int, ...] = (),
) -> str:
    """Decode and hash one deterministic representative video frame."""

    args = ["ffmpeg", "-v", "error", "-i", str(path), "-ss", f"{timestamp:.9f}"]
    if video_filter is not None:
        args.extend(["-vf", video_filter])
    args.extend(["-map", "0:v:0", "-an", "-frames:v", "1", "-f", "framemd5", "-"])
    values = _parse_frame_hashes(_run_command(args, pass_fds=pass_fds).stdout)
    if len(values) != 1:
        raise _salvage_error("representative frame hash is unavailable", "salvage_verification_failed")
    return values[0]


def _crop_origin_check(
    source: Path,
    output: Path,
    region: dict[str, float],
    *,
    claim: str,
    pass_fds: tuple[int, ...] = (),
) -> PreservationCheck:
    """Independently crop three source frames and compare their output peers."""

    info = _probe_source(source, pass_fds=pass_fds)
    width, height = round(info.width * region["width"]), round(info.height * region["height"])
    x, y = round(info.width * region["x"]), round(info.height * region["y"])
    crop_filter = _crop_filter(width, height, x, y)
    final_time = max(0.0, info.duration - (1.0 / info.fps))
    timestamps = (0.0, info.duration / 2.0, final_time)
    source_hashes = tuple(
        _decoded_frame_hash_at(source, timestamp, crop_filter, pass_fds=pass_fds) for timestamp in timestamps
    )
    output_hashes = tuple(_decoded_frame_hash_at(output, timestamp) for timestamp in timestamps)
    mismatches = sum(expected != observed for expected, observed in zip(source_hashes, output_hashes, strict=True))
    return PreservationCheck(
        claim=claim,
        passed=mismatches == 0,
        expected=f"representative_frames:{len(timestamps)};mismatches:0",
        observed=f"representative_frames:{len(timestamps)};mismatches:{mismatches}",
    )


def _still_frame_origin_check(
    source: Path,
    output: Path,
    timestamp: float,
    *,
    pass_fds: tuple[int, ...] = (),
) -> PreservationCheck:
    """Independently decode the declared source timestamp and compare pixels."""

    rgb_filter = "format=rgb24"
    expected_hash = _decoded_frame_hash_at(source, timestamp, rgb_filter, pass_fds=pass_fds)
    observed_hash = _decoded_frame_hash_at(output, 0.0, rgb_filter)
    return PreservationCheck(
        claim="still_frame_source_timestamp",
        passed=expected_hash == observed_hash,
        expected=expected_hash,
        observed=observed_hash,
    )


def _region_crop_origin_check(
    source: Path,
    output: Path,
    region: dict[str, float],
    *,
    pass_fds: tuple[int, ...] = (),
) -> PreservationCheck:
    """Independently render the declared crop and compare every frame hash."""

    info = _probe_source(source, pass_fds=pass_fds)
    width, height = round(info.width * region["width"]), round(info.height * region["height"])
    x, y = round(info.width * region["x"]), round(info.height * region["y"])
    crop_filter = _crop_filter(width, height, x, y)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".crop-verify.") as work:
        expected = Path(work) / "expected.mp4"
        _run_ffmpeg(
            [
                "-i",
                str(source),
                "-vf",
                crop_filter,
                "-c:v",
                "libx264",
                "-preset",
                DEFAULT_PRESET,
                "-crf",
                str(DEFAULT_CRF),
                "-c:a",
                "copy",
                str(expected),
            ],
            pass_fds=pass_fds,
        )
        expected_hashes = _decoded_frame_hashes(expected)
    observed_hashes = _decoded_frame_hashes(output)
    mismatches = sum(expected != observed for expected, observed in zip(expected_hashes, observed_hashes, strict=False))
    passed = mismatches == 0 and len(expected_hashes) == len(observed_hashes)
    return PreservationCheck(
        claim="requested_region_pixels",
        passed=passed,
        expected=f"frames:{len(expected_hashes)};mismatches:0",
        observed=f"frames:{len(observed_hashes)};mismatches:{mismatches}",
    )


def _audio_removed_check(output_info: Any) -> PreservationCheck:
    return PreservationCheck(
        claim="audio_removed",
        passed=output_info.audio_codec is None,
        expected="absent",
        observed="absent" if output_info.audio_codec is None else "present",
    )


def _source_unchanged_check(expected: str, observed: str) -> PreservationCheck:
    return PreservationCheck(
        claim="source_unchanged", passed=observed == expected, expected=expected, observed=observed
    )


def _duration_check(observed: float, expected: float) -> PreservationCheck:
    passed = abs(observed - expected) <= DEFAULT_SALVAGE_DURATION_TOLERANCE_SECONDS
    return PreservationCheck(
        claim="duration_policy", passed=passed, expected=f"{expected:.6f}", observed=f"{observed:.6f}"
    )


def _freeze_checks(
    source: Path,
    output: Path,
    *,
    pass_fds: tuple[int, ...] = (),
) -> tuple[PreservationCheck, ...]:
    """Bind every pre-transition, transition, and extension frame to source."""

    source_hashes = _decoded_frame_hashes(source, pass_fds=pass_fds)
    output_hashes = _decoded_frame_hashes(output)
    if len(output_hashes) < len(source_hashes):
        raise _salvage_error("freeze output is shorter than source", "salvage_verification_failed")
    source_tail = source_hashes[-1]
    transition_index = len(source_hashes) - 1
    output_tail = output_hashes[transition_index]
    extension_hashes = output_hashes[transition_index:]
    extension_mismatches = sum(value != source_tail for value in extension_hashes)
    prefix_pairs = tuple(zip(source_hashes, output_hashes[: len(source_hashes)], strict=True))
    prefix_mismatches = sum(expected != observed for expected, observed in prefix_pairs)
    return (
        PreservationCheck(
            claim="freeze_source_tail_match",
            passed=output_tail == source_tail,
            expected=source_tail,
            observed=output_tail,
        ),
        PreservationCheck(
            claim="freeze_extension_frames_identical",
            passed=extension_mismatches == 0,
            expected=source_tail,
            observed=f"frames:{len(extension_hashes)};mismatches:{extension_mismatches}",
        ),
        PreservationCheck(
            claim="freeze_prefix_source_match",
            passed=prefix_mismatches == 0,
            expected=f"frames:{len(source_hashes)};mismatches:0",
            observed=f"frames:{len(source_hashes)};mismatches:{prefix_mismatches}",
        ),
    )


def _clean_edges_origin_check(
    source: Path,
    output: Path,
    policy: dict[str, Any],
    *,
    pass_fds: tuple[int, ...] = (),
) -> PreservationCheck:
    """Compare output frames with an independently selected source interval."""

    start = _escape_ffmpeg_filter_value(str(policy["trim_start"]))
    duration = _probe_source(source, pass_fds=pass_fds).duration
    end = _escape_ffmpeg_filter_value(str(duration - policy["trim_end"]))
    select = f"select=gte(t\\,{start})*lt(t\\,{end}),setpts=N/FRAME_RATE/TB"
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".clean-verify.") as work:
        expected = Path(work) / "expected.mp4"
        _run_ffmpeg(
            [
                "-i",
                str(source),
                "-vf",
                select,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                DEFAULT_PRESET,
                "-crf",
                str(DEFAULT_CRF),
                str(expected),
            ],
            pass_fds=pass_fds,
        )
        expected_hashes = _decoded_frame_hashes(expected)
    observed_hashes = _decoded_frame_hashes(output)
    passed = observed_hashes == expected_hashes
    return PreservationCheck(
        claim="clean_edges_source_interval",
        passed=passed,
        expected=f"frames:{len(expected_hashes)};mismatches:0",
        observed=f"frames:{len(observed_hashes)};match:{str(passed).lower()}",
    )
