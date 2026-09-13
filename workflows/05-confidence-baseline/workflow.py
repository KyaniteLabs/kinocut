#!/usr/bin/env python3
"""Confidence baseline workflow for Kinocut."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from kinocut import Client
from kinocut.defaults import (
    DEFAULT_FFMPEG_TIMEOUT,
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
    DEFAULT_QUALITY_GATE_SCORE,
)
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.source_identity import stream_source_identity


WORKFLOW_DIR = Path(__file__).resolve().parent
ROOT = WORKFLOW_DIR.parents[1]
OUTPUT_DIR = WORKFLOW_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(" ".join(cmd), 124, f"FFmpeg timed out after {DEFAULT_FFMPEG_TIMEOUT}s") from exc
    except subprocess.CalledProcessError as exc:
        raise ProcessingError(" ".join(cmd), exc.returncode, exc.stderr or "") from exc
    except OSError as exc:
        raise ProcessingError(" ".join(cmd), 126, str(exc)) from exc


def _generate_source(path: Path) -> None:
    _run(
        [
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
            str(path),
        ]
    )


def _commit_identity() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MCPVideoError(
            "Candidate commit cannot be verified",
            error_type="validation_error",
            code="candidate_identity_unavailable",
        ) from exc
    commit = result.stdout.strip()
    configured = os.environ.get("GITHUB_SHA")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or (configured is not None and configured != commit):
        raise MCPVideoError(
            "Candidate commit does not match the checked-out full Git SHA",
            error_type="validation_error",
            code="candidate_identity_mismatch",
        )
    return commit


def _validate_raw_quality(quality: dict[str, Any]) -> None:
    score = quality.get("overall_score")
    checks = quality.get("checks")
    try:
        numeric_score = float(score) if not isinstance(score, bool) and isinstance(score, (int, float)) else math.nan
    except (OverflowError, TypeError, ValueError):
        numeric_score = math.nan
    if (
        quality.get("all_passed") is not True
        or not math.isfinite(numeric_score)
        or numeric_score < DEFAULT_QUALITY_GATE_SCORE
    ):
        raise MCPVideoError(
            "The raw quality gate did not pass at score 80 or higher",
            error_type="validation_error",
            code="raw_quality_failed",
        )
    if not isinstance(checks, list) or not checks:
        raise MCPVideoError("The raw quality gate has no checks", "validation_error", "raw_quality_failed")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            raise MCPVideoError(
                "The raw quality gate contains an invalid check", "validation_error", "raw_quality_failed"
            )
        if check["name"] != "temporal_motion" and check.get("passed") is not True:
            raise MCPVideoError("A non-advisory raw quality check failed", "validation_error", "raw_quality_failed")


def _edit_video(client: Any, source: Path, trim_duration: float, tool_calls: list[dict[str, Any]]) -> str:
    print("\n[1/7] Trimming proof segment...")
    trimmed = client.trim(
        str(source),
        start="00:00:00",
        duration=str(int(trim_duration)),
        output=str(OUTPUT_DIR / "01_trimmed.mp4"),
    )
    tool_calls.append({"stage": "01-trim", "tool": "Client.trim", "output": _value(trimmed, "output_path")})

    print("\n[2/7] Resizing to vertical 9:16...")
    vertical = client.resize(
        _value(trimmed, "output_path"),
        aspect_ratio="9:16",
        output=str(OUTPUT_DIR / "02_vertical.mp4"),
    )
    tool_calls.append({"stage": "02-resize", "tool": "Client.resize", "output": _value(vertical, "output_path")})

    print("\n[3/7] Adding proof caption...")
    captioned = client.add_text(
        _value(vertical, "output_path"),
        text="Kinocut proof",
        position="top-center",
        size=42,
        color="#CCFF00",
        start_time=0,
        duration=min(4, int(trim_duration)),
        output=str(OUTPUT_DIR / "03_captioned.mp4"),
    )
    tool_calls.append({"stage": "03-caption", "tool": "Client.add_text", "output": _value(captioned, "output_path")})

    print("\n[4/7] Normalizing audio...")
    normalized = client.normalize_audio(
        _value(captioned, "output_path"),
        target_lufs=-14.0,
        output=str(OUTPUT_DIR / "04_normalized.mp4"),
    )
    tool_calls.append(
        {"stage": "04-normalize", "tool": "Client.normalize_audio", "output": _value(normalized, "output_path")}
    )

    print("\n[5/7] Exporting final MP4...")
    final = client.convert(
        _value(normalized, "output_path"),
        format="mp4",
        quality="high",
        output=str(OUTPUT_DIR / "final_clip.mp4"),
    )
    final_path = _value(final, "output_path")
    tool_calls.append({"stage": "05-export", "tool": "Client.convert", "output": final_path})
    return final_path


def _quality_and_checkpoint(
    client: Any, final_path: str, tool_calls: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    print("\n[6/7] Running quality and release checkpoint...")
    quality = client.quality_check(final_path, fail_on_warning=True)
    quality_json = quality if isinstance(quality, dict) else quality.model_dump()
    _validate_raw_quality(quality_json)
    checkpoint = client.release_checkpoint(
        final_path,
        output_dir=str(OUTPUT_DIR / "checkpoint"),
        min_score=DEFAULT_QUALITY_GATE_SCORE,
        frame_count=4,
    )
    tool_calls.append(
        {"stage": "06-quality", "tool": "Client.quality_check", "output": str(OUTPUT_DIR / "quality.json")}
    )
    tool_calls.append(
        {"stage": "06-checkpoint", "tool": "Client.release_checkpoint", "output": str(OUTPUT_DIR / "checkpoint")}
    )

    checkpoint_json = checkpoint if isinstance(checkpoint, dict) else checkpoint.model_dump()
    (OUTPUT_DIR / "quality.json").write_text(
        json.dumps(quality_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "release_checkpoint.json").write_text(
        json.dumps(checkpoint_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return quality_json, checkpoint_json


def _receipt(
    *,
    run_id: str,
    candidate_commit: str,
    source: Path,
    source_before: Any,
    info: Any,
    duration: float,
    tool_calls: list[dict[str, Any]],
    final_path: str,
    quality: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "candidate": {"package": "kinocut", "version": version("kinocut"), "commit": candidate_commit},
        "user_intent": "Prove Kinocut can produce a checked vertical video from generated or local source media.",
        "source_media": {
            "path": str(source),
            "sha256": source_before.asset_id,
            "byte_size": source_before.byte_size,
            "duration_seconds": duration,
            "width": _value(info, "width"),
            "height": _value(info, "height"),
        },
        "tool_calls": tool_calls,
        "edits_applied": [
            "trimmed source clip",
            "resized to 9:16",
            "added proof caption",
            "normalized audio",
            "exported final MP4",
            "created release checkpoint",
        ],
        "guardrails_triggered": quality.get("recommendations", []),
        "quality": {
            "all_passed": quality.get("all_passed"),
            "overall_score": quality.get("overall_score"),
            "recommendations": quality.get("recommendations", []),
        },
        "review_artifacts": {
            "final_video": final_path,
            "final_sha256": stream_source_identity(final_path).asset_id,
            "quality_report": str(OUTPUT_DIR / "quality.json"),
            "release_checkpoint": str(OUTPUT_DIR / "release_checkpoint.json"),
            "thumbnail": checkpoint.get("thumbnail"),
            "storyboard": checkpoint.get("storyboard", {}).get("frames", []),
        },
        "human_review": {
            "required": True,
            "status": "pending",
            "instructions": checkpoint.get(
                "instructions",
                "Open final video, thumbnail, and storyboard before publishing.",
            ),
        },
        "known_limitations": [
            "Automated quality checks do not replace visual/audio review.",
            "Synthetic source media proves plumbing, not creative quality.",
        ],
        "next_edit_suggestion": "Inspect the storyboard and adjust caption, crop, or audio if the final clip is intended for publication.",
    }


def main() -> None:
    print("=" * 60)
    print("05-confidence-baseline workflow")
    print("=" * 60)
    client = Client()
    candidate_commit = _commit_identity()
    source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else OUTPUT_DIR / "source.mp4"
    tool_calls: list[dict[str, Any]] = []
    if not source.exists():
        print("\n[0/7] Generating synthetic source clip...")
        _generate_source(source)
        print(f"   -> {source}")
    source_before = stream_source_identity(str(source))
    run_id = os.environ.get(
        "KINOCUT_GOLDEN_RUN_ID", "standalone-" + source_before.asset_id.removeprefix("sha256:")[:16]
    )
    info = client.info(str(source))
    duration = float(_value(info, "duration", 0) or 0)
    final_path = _edit_video(client, source, min(6.0, duration) if duration else 4.0, tool_calls)
    quality, checkpoint = _quality_and_checkpoint(client, final_path, tool_calls)
    receipt = _receipt(
        run_id=run_id,
        candidate_commit=candidate_commit,
        source=source,
        source_before=source_before,
        info=info,
        duration=duration,
        tool_calls=tool_calls,
        final_path=final_path,
        quality=quality,
        checkpoint=checkpoint,
    )
    print("\n[7/7] Writing Video Receipt...")
    if stream_source_identity(str(source)) != source_before:
        raise ProcessingError("source-integrity", 1, "Source changed during confidence workflow")
    receipt_path = OUTPUT_DIR / "video_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"   -> {receipt_path}")

    print("\n" + "=" * 60)
    print("Confidence baseline complete. Human review is still required.")
    print("=" * 60)


if __name__ == "__main__":
    main()
