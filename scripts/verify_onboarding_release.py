#!/usr/bin/env python3
"""Verify one clean-wheel timed-caption release journey outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.defaults import (
    DEFAULT_ONBOARDING_FIXTURE_AUDIO_CODEC,
    DEFAULT_ONBOARDING_FIXTURE_AUDIO_VOLUME,
    DEFAULT_ONBOARDING_FIXTURE_DURATION_SECONDS,
    DEFAULT_ONBOARDING_FIXTURE_EQ_BRIGHTNESS,
    DEFAULT_ONBOARDING_FIXTURE_EQ_CONTRAST,
    DEFAULT_ONBOARDING_FIXTURE_EQ_SATURATION,
    DEFAULT_ONBOARDING_FIXTURE_FRAME_RATE,
    DEFAULT_ONBOARDING_FIXTURE_HEIGHT,
    DEFAULT_ONBOARDING_FIXTURE_PIXEL_FORMAT,
    DEFAULT_ONBOARDING_FIXTURE_SAMPLE_RATE_HZ,
    DEFAULT_ONBOARDING_FIXTURE_SINE_FREQUENCY_HZ,
    DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_COLOR,
    DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_HEIGHT,
    DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_START_ROW,
    DEFAULT_ONBOARDING_FIXTURE_VIDEO_CODEC,
    DEFAULT_ONBOARDING_FIXTURE_WIDTH,
)

DEFAULT_TIMEOUT = 600.0
QUALITY_SCORE = 80.0
DURATION_SECONDS = DEFAULT_ONBOARDING_FIXTURE_DURATION_SECONDS
FRAME_TIMES = (("outside_0.25", 0.25), ("cue_1.20", 1.2), ("outside_2.60", 2.6), ("cue_4.00", 4.0))
ADVISORY_CHECKS = frozenset({"temporal_motion"})
MAX_DIAGNOSTIC_CHARS = 1000
CHANNEL_DELTA = 24
MINIMUM_CUE_CHANGED_PIXELS = 1000
CUE_TO_OUTSIDE_CHANGED_PIXEL_MULTIPLIER = 5
MINIMUM_CUE_CROP_SSIM_DELTA = 0.002
MINIMUM_OUTSIDE_FULL_FRAME_SSIM = 0.99


class AcceptanceError(MCPVideoError):
    """One bounded release-acceptance failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_type="validation_error", code="onboarding_release_failed")


def _bounded(value: object) -> str:
    return str(value or "")[-MAX_DIAGNOSTIC_CHARS:]


def _finite_number(value: object, label: str, *, allow_text: bool = False) -> float:
    valid_type = isinstance(value, (int, float)) or (allow_text and isinstance(value, str))
    if isinstance(value, bool) or not valid_type:
        raise AcceptanceError(f"{label} must be finite and numeric")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise AcceptanceError(f"{label} must be finite and numeric") from exc
    if not math.isfinite(number):
        raise AcceptanceError(f"{label} must be finite and numeric")
    return number


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run(
    cmd: list[str], *, cwd: Path, timeout: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env or _clean_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AcceptanceError(
            f"command timed out after {timeout:g}s: {cmd[0]}\n{_bounded(exc.stderr or exc.stdout)}"
        ) from exc
    except OSError as exc:
        raise AcceptanceError(f"cannot start command {cmd[0]}: {_bounded(exc)}") from exc


def _checked(cmd: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    result = _run(cmd, cwd=cwd, timeout=timeout)
    if result.returncode:
        raise AcceptanceError(
            f"command exited {result.returncode}: {cmd[0]}\n{_bounded(result.stderr or result.stdout)}"
        )
    return result


def _json_output(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"{label} returned malformed JSON: {_bounded(exc)}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} must return a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise AcceptanceError(f"cannot hash {path.name}: {_bounded(exc)}") from exc
    return "sha256:" + digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"{label} must be a regular non-symlink file")
    return path.resolve(strict=True)


def _interpreter(path: Path, checkout: Path) -> Path:
    lexical = path.expanduser().absolute()
    if not lexical.is_file():
        raise AcceptanceError("Python interpreter must be an existing file")
    _require_outside_checkout(lexical, checkout, "Python interpreter")
    return lexical


def _require_outside_checkout(path: Path, checkout: Path, label: str) -> Path:
    resolved = path.resolve(strict=False)
    root = checkout.resolve(strict=True)
    if resolved == root or root in resolved.parents:
        raise AcceptanceError(f"{label} must resolve outside the checkout")
    return resolved


def _fresh_output(path: Path, checkout: Path) -> Path:
    output = _require_outside_checkout(path, checkout, "output directory")
    if path.is_symlink():
        raise AcceptanceError("output directory must not be a symlink")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise AcceptanceError("output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    return output.resolve(strict=True)


def _wheel_version(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as wheel:
            metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise AcceptanceError("wheel must contain exactly one distribution METADATA file")
            text = wheel.read(metadata[0]).decode("utf-8")
    except (OSError, UnicodeError, zipfile.BadZipFile, KeyError) as exc:
        raise AcceptanceError(f"wheel metadata cannot be read: {_bounded(exc)}") from exc
    fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
    if fields.get("Name", "").lower() != "kinocut" or not fields.get("Version"):
        raise AcceptanceError("wheel METADATA must identify a versioned Kinocut distribution")
    return fields["Version"]


def _validate_quality(quality: dict[str, Any]) -> None:
    score = quality.get("overall_score")
    if quality.get("all_passed") is not True:
        raise AcceptanceError("raw quality all_passed must be literal true")
    if _finite_number(score, "raw quality score") < QUALITY_SCORE:
        raise AcceptanceError(f"raw quality score must be at least {QUALITY_SCORE:g}")
    checks = quality.get("checks")
    if not isinstance(checks, list) or not checks:
        raise AcceptanceError("raw quality checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            raise AcceptanceError("raw quality check entries must be named objects")
        if check["name"] not in ADVISORY_CHECKS and check.get("passed") is not True:
            raise AcceptanceError(f"non-advisory raw quality check failed: {check['name']}")


def _inside_output(value: object, output: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AcceptanceError(f"{label} path is missing")
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise AcceptanceError(f"{label} is missing: {_bounded(exc)}") from exc
    if not path.is_file() or output not in path.parents:
        raise AcceptanceError(f"{label} must be a file inside the output directory")
    return path


def _validate_checkpoint(checkpoint: dict[str, Any], output: Path | None = None) -> None:
    quality = checkpoint.get("quality")
    score = quality.get("overall_score") if isinstance(quality, dict) else None
    if (
        _finite_number(score, "checkpoint quality score") < QUALITY_SCORE
        or checkpoint.get("review_required") is not True
    ):
        raise AcceptanceError("checkpoint did not reach the review gate")
    storyboard = checkpoint.get("storyboard")
    frames = storyboard.get("frames") if isinstance(storyboard, dict) else None
    if not isinstance(frames, list) or not frames:
        raise AcceptanceError("checkpoint storyboard frames are missing")
    if output is not None:
        _inside_output(checkpoint.get("thumbnail"), output, "checkpoint thumbnail")
        for frame in frames:
            _inside_output(frame, output, "checkpoint storyboard frame")


def _validate_probe(probe: dict[str, Any], expected_duration: float) -> None:
    streams = probe.get("streams")
    container = probe.get("format")
    if not isinstance(streams, list) or not isinstance(container, dict):
        raise AcceptanceError("ffprobe output is missing streams or format")
    videos = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise AcceptanceError("final output must contain exactly one video stream")
    if not audio:
        raise AcceptanceError("final output must contain at least one audio stream")
    if (videos[0].get("width"), videos[0].get("height")) != (1080, 1920):
        raise AcceptanceError("final output must be 1080x1920")
    try:
        duration_value = container["duration"]
    except KeyError as exc:
        raise AcceptanceError("final output duration must be finite") from exc
    duration = _finite_number(duration_value, "final output duration", allow_text=True)
    if duration <= 0 or abs(duration - expected_duration) > 0.75:
        raise AcceptanceError("final output duration is outside the accepted tolerance")
    if "mp4" not in str(container.get("format_name", "")).split(","):
        raise AcceptanceError("final output must use an MP4-family container")


def _validate_temporal_metrics(metrics: dict[str, dict[str, float | int]]) -> None:
    outside = [metrics[name] for name, _ in FRAME_TIMES if name.startswith("outside_")]
    cues = [metrics[name] for name, _ in FRAME_TIMES if name.startswith("cue_")]
    max_outside = max(int(metric["changed_pixels"]) for metric in outside)
    min_outside_crop = min(float(metric["crop_ssim"]) for metric in outside)
    if any(float(metric["full_ssim"]) < MINIMUM_OUTSIDE_FULL_FRAME_SSIM for metric in outside):
        raise AcceptanceError(f"outside-cue full-frame SSIM must be at least {MINIMUM_OUTSIDE_FULL_FRAME_SSIM:g}")
    for metric in cues:
        if int(metric["changed_pixels"]) < MINIMUM_CUE_CHANGED_PIXELS or int(metric["changed_pixels"]) < (
            CUE_TO_OUTSIDE_CHANGED_PIXEL_MULTIPLIER * max_outside
        ):
            raise AcceptanceError("cue changed pixels did not exceed the temporal threshold")
        if float(metric["crop_ssim"]) > min_outside_crop - MINIMUM_CUE_CROP_SSIM_DELTA:
            raise AcceptanceError("cue crop SSIM did not separate from outside-cue frames")


def _temporal_evidence(metrics: dict[str, dict[str, float | int]]) -> dict[str, Any]:
    return {
        "temporal_metrics": metrics,
        "temporal_tolerances": {
            "channel_delta": CHANNEL_DELTA,
            "minimum_cue_changed_pixels": MINIMUM_CUE_CHANGED_PIXELS,
            "cue_to_outside_changed_pixel_multiplier": CUE_TO_OUTSIDE_CHANGED_PIXEL_MULTIPLIER,
            "minimum_cue_crop_ssim_delta": MINIMUM_CUE_CROP_SSIM_DELTA,
            "minimum_outside_full_frame_ssim": MINIMUM_OUTSIDE_FULL_FRAME_SSIM,
        },
    }


def _installed_identity(python: Path, kino: Path, version: str, checkout: Path, cwd: Path, timeout: float) -> dict:
    code = (
        "import importlib.metadata,inspect,json,sys,kinocut,mcp_video;"
        "from kinocut import Client;method=Client.release_checkpoint;"
        "print(json.dumps({'version':importlib.metadata.version('kinocut'),"
        "'prefix':sys.prefix,'executable':sys.executable,"
        "'kinocut':kinocut.__file__,'mcp_video':mcp_video.__file__,"
        "'release_checkpoint_callable':callable(method),"
        "'release_checkpoint_origin':inspect.getsourcefile(method)}))"
    )
    identity = _json_output(_checked([str(python), "-c", code], cwd=cwd, timeout=timeout), "installed identity")
    if identity.get("version") != version:
        raise AcceptanceError("installed version does not match wheel METADATA")
    prefix_value = identity.get("prefix")
    executable_value = identity.get("executable")
    if not isinstance(prefix_value, str) or not isinstance(executable_value, str):
        raise AcceptanceError("selected venv identity is incomplete")
    try:
        prefix = Path(prefix_value).resolve(strict=True)
    except OSError as exc:
        raise AcceptanceError(f"selected venv prefix is invalid: {_bounded(exc)}") from exc
    selected_prefix = python.parent.parent.resolve(strict=True)
    if not prefix.is_dir() or prefix != selected_prefix:
        raise AcceptanceError("reported interpreter prefix does not match the selected venv")
    if Path(executable_value).absolute() != python.absolute():
        raise AcceptanceError("reported executable does not match the selected venv launcher")
    _require_outside_checkout(prefix, checkout, "selected venv")
    if prefix not in kino.resolve(strict=True).parents:
        raise AcceptanceError("kino console script is outside the selected venv")
    for label in ("kinocut", "mcp_video"):
        value = identity.get(label)
        if not isinstance(value, str):
            raise AcceptanceError(f"installed {label} path is missing")
        facade = _regular(Path(value), f"installed {label}")
        _require_outside_checkout(facade, checkout, label)
        if prefix not in facade.parents:
            raise AcceptanceError(f"installed {label} is outside the selected venv")
    if identity.get("release_checkpoint_callable") is not True:
        raise AcceptanceError("installed Client.release_checkpoint must be callable")
    origin_value = identity.get("release_checkpoint_origin")
    if not isinstance(origin_value, str):
        raise AcceptanceError("installed Client.release_checkpoint origin is missing")
    origin = _regular(Path(origin_value), "installed Client.release_checkpoint origin")
    _require_outside_checkout(origin, checkout, "Client.release_checkpoint")
    if prefix not in origin.parents:
        raise AcceptanceError("installed Client.release_checkpoint is outside the selected venv")
    first_line = kino.read_text(encoding="utf-8").splitlines()[0]
    if first_line != f"#!{python}":
        raise AcceptanceError("kino console script does not use the selected clean-venv interpreter")
    return identity


def _checkout_commit(checkout: Path, cwd: Path, timeout: float) -> str:
    result = _checked(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=cwd, timeout=timeout)
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise AcceptanceError("checked-out candidate commit is not a full lowercase Git SHA")
    return commit


def _source_identity(python: Path, source: Path, cwd: Path, timeout: float) -> dict[str, Any]:
    code = (
        "import json,sys;from kinocut.source_identity import stream_source_identity;"
        "x=stream_source_identity(sys.argv[1]);print(json.dumps({'sha256':x.asset_id,'byte_size':x.byte_size}))"
    )
    identity = _json_output(
        _checked([str(python), "-c", code, str(source)], cwd=cwd, timeout=timeout), "source identity"
    )
    sha256 = identity.get("sha256")
    byte_size = identity.get("byte_size")
    if not isinstance(sha256, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", sha256) is None:
        raise AcceptanceError("source identity SHA-256 is malformed")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 1:
        raise AcceptanceError("source identity byte size must be a positive integer")
    return identity


def _generate_source(source: Path, cwd: Path, timeout: float) -> tuple[str, str]:
    if source.exists():
        raise AcceptanceError("synthetic source destination must be fresh")
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        (
            f"testsrc2=size={DEFAULT_ONBOARDING_FIXTURE_WIDTH}x{DEFAULT_ONBOARDING_FIXTURE_HEIGHT}"
            f":rate={DEFAULT_ONBOARDING_FIXTURE_FRAME_RATE}"
        ),
        "-f",
        "lavfi",
        "-i",
        (
            f"sine=frequency={DEFAULT_ONBOARDING_FIXTURE_SINE_FREQUENCY_HZ}"
            f":sample_rate={DEFAULT_ONBOARDING_FIXTURE_SAMPLE_RATE_HZ}"
        ),
        "-t",
        f"{DEFAULT_ONBOARDING_FIXTURE_DURATION_SECONDS:g}",
        "-vf",
        (
            f"eq=contrast={DEFAULT_ONBOARDING_FIXTURE_EQ_CONTRAST:g}"
            f":brightness={DEFAULT_ONBOARDING_FIXTURE_EQ_BRIGHTNESS:g}"
            f":saturation={DEFAULT_ONBOARDING_FIXTURE_EQ_SATURATION:g},"
            f"drawbox=x=0:y={DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_START_ROW}"
            f":w={DEFAULT_ONBOARDING_FIXTURE_WIDTH}:h={DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_HEIGHT}"
            f":color={DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_COLOR}:t=fill"
        ),
        "-af",
        f"volume={DEFAULT_ONBOARDING_FIXTURE_AUDIO_VOLUME:g}",
        "-c:v",
        DEFAULT_ONBOARDING_FIXTURE_VIDEO_CODEC,
        "-pix_fmt",
        DEFAULT_ONBOARDING_FIXTURE_PIXEL_FORMAT,
        "-c:a",
        DEFAULT_ONBOARDING_FIXTURE_AUDIO_CODEC,
        str(source),
    ]
    _checked(command, cwd=cwd, timeout=timeout)
    version = _checked(["ffmpeg", "-version"], cwd=cwd, timeout=timeout).stdout.splitlines()[0]
    return shlex.join([*command[:-1], "SOURCE"]), version


def _require_subtitles_filter(cwd: Path, timeout: float) -> None:
    filters = _checked(["ffmpeg", "-hide_banner", "-filters"], cwd=cwd, timeout=timeout)
    available = any(
        len(fields) >= 3 and fields[1] == "subtitles" and fields[2] == "V->V"
        for fields in (line.split() for line in filters.stdout.splitlines())
    )
    if not available:
        raise AcceptanceError("FFmpeg subtitles filter is unavailable")


def _cli_journey(kino: Path, source: Path, captions: Path, output: Path, timeout: float) -> tuple[dict, list]:
    commands = [
        [str(kino), "doctor", "--json"],
        [str(kino), "trim", str(source), "--start", "0", "--duration", "6", "--output", str(output / "01-trimmed.mp4")],
        [
            str(kino),
            "resize",
            str(output / "01-trimmed.mp4"),
            "--aspect-ratio",
            "9:16",
            "--output",
            str(output / "02-vertical.mp4"),
        ],
        [
            str(kino),
            "subtitles",
            str(output / "02-vertical.mp4"),
            str(captions),
            "--output",
            str(output / "03-captioned.mp4"),
        ],
        [
            str(kino),
            "normalize-audio",
            str(output / "03-captioned.mp4"),
            "--lufs",
            "-14",
            "--output",
            str(output / "final.mp4"),
        ],
    ]
    doctor = _json_output(_checked(commands[0], cwd=output, timeout=timeout), "kino doctor")
    if not isinstance(doctor.get("summary"), dict) or doctor["summary"].get("required_ok") is not True:
        raise AcceptanceError("kino doctor summary.required_ok must be literal true")
    for command in commands[1:]:
        _checked(command, cwd=output, timeout=timeout)
        _regular(Path(command[-1]), "journey output")
    quality_command = [
        str(kino),
        "video-quality-check",
        str(output / "final.mp4"),
        "--fail-on-warning",
        "--format",
        "json",
    ]
    quality = _json_output(_checked(quality_command, cwd=output, timeout=timeout), "raw quality")
    _validate_quality(quality)
    return quality, [*commands, quality_command]


def _checkpoint(python: Path, final: Path, output: Path, timeout: float) -> dict[str, Any]:
    code = (
        "import json,sys;from kinocut import Client;"
        "x=Client().release_checkpoint(sys.argv[1],output_dir=sys.argv[2],min_score=80,frame_count=4);"
        "print(json.dumps(x.model_dump() if hasattr(x,'model_dump') else x))"
    )
    checkpoint = _json_output(
        _checked([str(python), "-c", code, str(final), str(output / "checkpoint")], cwd=output, timeout=timeout),
        "release checkpoint",
    )
    _validate_checkpoint(checkpoint, output)
    return checkpoint


def _probe_and_decode(final: Path, output: Path, timeout: float) -> dict[str, Any]:
    probe_command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(final)]
    probe = _json_output(_checked(probe_command, cwd=output, timeout=timeout), "ffprobe")
    _validate_probe(probe, DURATION_SECONDS)
    _checked(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(final), "-map", "0", "-f", "null", "-"],
        cwd=output,
        timeout=timeout,
    )
    return probe


def _rgb_frame(video: Path, timestamp: float, output: Path, timeout: float) -> bytes:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{timestamp:.2f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    try:
        result = subprocess.run(cmd, cwd=output, env=_clean_env(), capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AcceptanceError(f"frame extraction timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise AcceptanceError(f"cannot extract frame: {_bounded(exc)}") from exc
    expected_size = DEFAULT_ONBOARDING_FIXTURE_WIDTH * DEFAULT_ONBOARDING_FIXTURE_HEIGHT * 3
    if result.returncode or len(result.stdout) != expected_size:
        raise AcceptanceError(f"frame extraction failed: {_bounded(result.stderr)}")
    return result.stdout


def _ssim(first: bytes, second: bytes) -> float:
    values = len(first) // 3
    if values == 0 or len(first) != len(second):
        raise AcceptanceError("frame buffers do not match")
    sums = [0.0] * 5
    for index in range(0, len(first), 3):
        x = (first[index] + first[index + 1] + first[index + 2]) / 3
        y = (second[index] + second[index + 1] + second[index + 2]) / 3
        sums[0] += x
        sums[1] += y
        sums[2] += x * x
        sums[3] += y * y
        sums[4] += x * y
    mean_x, mean_y = sums[0] / values, sums[1] / values
    var_x = max(0.0, sums[2] / values - mean_x * mean_x)
    var_y = max(0.0, sums[3] / values - mean_y * mean_y)
    covariance = sums[4] / values - mean_x * mean_y
    return ((2 * mean_x * mean_y + 6.5025) * (2 * covariance + 58.5225)) / (
        (mean_x * mean_x + mean_y * mean_y + 6.5025) * (var_x + var_y + 58.5225)
    )


def _frame_metrics(before: Path, after: Path, output: Path, timeout: float) -> dict[str, dict[str, float | int]]:
    metrics: dict[str, dict[str, float | int]] = {}
    crop_offset = DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_START_ROW * DEFAULT_ONBOARDING_FIXTURE_WIDTH * 3
    crop_length = DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_HEIGHT * DEFAULT_ONBOARDING_FIXTURE_WIDTH * 3
    for label, timestamp in FRAME_TIMES:
        first = _rgb_frame(before, timestamp, output, timeout)
        second = _rgb_frame(after, timestamp, output, timeout)
        first_crop = first[crop_offset : crop_offset + crop_length]
        second_crop = second[crop_offset : crop_offset + crop_length]
        if len(first_crop) != crop_length or len(second_crop) != crop_length:
            raise AcceptanceError("frame crop does not match the stable fixture region")
        changed = sum(
            max(abs(first_crop[i + channel] - second_crop[i + channel]) for channel in range(3)) >= CHANNEL_DELTA
            for i in range(0, len(first_crop), 3)
        )
        metrics[label] = {
            "changed_pixels": changed,
            "crop_ssim": _ssim(first_crop, second_crop),
            "full_ssim": _ssim(first, second),
        }
    _validate_temporal_metrics(metrics)
    return metrics


def _receipt_base(kind: str, commit: str, wheel: str, source: str, size: int, output: str, run: str) -> dict:
    limitation = (
        "Synthetic fixture evidence proves clean installation and timed changes, not caption readability or creative quality."
        if kind.startswith("synthetic")
        else "Real interview technical evidence uses supplied captions and does not prove transcription accuracy."
    )
    return {
        "schema": "kinocut.onboarding_release.v1",
        "run_id": run,
        "evidence_class": kind,
        "candidate": {"commit": commit, "wheel_sha256": wheel},
        "source_media": {"sha256": source, "byte_size": size},
        "final_output": {"sha256": output},
        "human_review": {"required": True, "status": "pending"},
        "limitations": [limitation, "Automated checks do not replace visual and audio review."],
    }


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--captions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--kino", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--evidence-class", choices=("synthetic_fixture", "real_interview"), required=True)
    parser.add_argument("--generate-synthetic-source", action="store_true")
    return parser.parse_args(argv)


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    checkout = Path(__file__).resolve().parents[1]
    if re.fullmatch(r"[0-9a-f]{40}", args.candidate_commit) is None:
        raise AcceptanceError("candidate commit must be a full lowercase Git SHA")
    args.timeout = _finite_number(args.timeout, "timeout")
    if args.timeout <= 0:
        raise AcceptanceError("timeout must be a positive finite number")
    wheel = _regular(args.wheel, "wheel")
    captions = _regular(args.captions, "captions")
    python = _interpreter(args.python, checkout)
    kino = _require_outside_checkout(_regular(args.kino, "kino console script"), checkout, "kino console script")
    output = _fresh_output(args.output_dir, checkout)
    if _checkout_commit(checkout, output, args.timeout) != args.candidate_commit:
        raise AcceptanceError("candidate commit does not match the checked-out source")
    source = _require_outside_checkout(args.source, checkout, "source")
    recipe = ffmpeg_version = None
    if args.generate_synthetic_source:
        if args.evidence_class != "synthetic_fixture":
            raise AcceptanceError("source generation is only valid for synthetic fixture evidence")
        source.parent.mkdir(parents=True, exist_ok=True)
        recipe, ffmpeg_version = _generate_source(source, source.parent, args.timeout)
    source = _regular(source, "source")
    _require_subtitles_filter(output, args.timeout)
    version = _wheel_version(wheel)
    installed = _installed_identity(python, kino, version, checkout, output, args.timeout)
    source_before = _source_identity(python, source, output, args.timeout)
    quality, commands = _cli_journey(kino, source, captions, output, args.timeout)
    checkpoint = _checkpoint(python, output / "final.mp4", output, args.timeout)
    probe = _probe_and_decode(output / "final.mp4", output, args.timeout)
    metrics = _frame_metrics(output / "02-vertical.mp4", output / "03-captioned.mp4", output, args.timeout)
    source_after = _source_identity(python, source, output, args.timeout)
    if source_after != source_before:
        raise AcceptanceError("source identity changed during the release journey")
    final_identity = _source_identity(python, output / "final.mp4", output, args.timeout)
    receipt = _receipt_base(
        args.evidence_class,
        args.candidate_commit,
        _sha256(wheel),
        source_before["sha256"],
        source_before["byte_size"],
        final_identity["sha256"],
        uuid.uuid4().hex,
    )
    receipt.update(
        {
            "created_at": datetime.now(UTC).isoformat(),
            "candidate": {**receipt["candidate"], "version": version},
            "installed_identity": {
                "version": installed["version"],
                "outside_checkout": True,
                "console_python": True,
                "selected_venv_prefix": True,
                "facades_inside_selected_venv": True,
                "release_checkpoint_callable": installed["release_checkpoint_callable"],
                "release_checkpoint_inside_selected_venv": True,
            },
            "journey": {
                "commands": [command[1] for command in commands],
                "client_calls": ["Client.release_checkpoint"],
                "cwd_outside_checkout": True,
            },
            "quality": quality,
            "checkpoint": {
                "review_required": checkpoint["review_required"],
                "thumbnail": Path(checkpoint["thumbnail"]).relative_to(output).as_posix(),
                "storyboard": [
                    Path(frame).relative_to(output).as_posix() for frame in checkpoint["storyboard"]["frames"]
                ],
            },
            "media": {"probe": probe, "full_decode": True, **_temporal_evidence(metrics)},
            "synthetic_fixture": {"recipe": recipe, "ffmpeg_version": ffmpeg_version} if recipe else None,
        }
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        receipt = _execute(args)
        destination = args.output_dir.resolve(strict=True) / "onboarding-release-receipt.json"
        destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (AcceptanceError, OSError, UnicodeError) as exc:
        print(f"FAIL: {_bounded(exc)}", file=sys.stderr)
        return 1
    print(f"ONBOARDING RELEASE TECHNICAL PASS: {destination}")
    print("Human visual/audio review remains required and pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
