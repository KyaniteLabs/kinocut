#!/usr/bin/env python3
"""Confidence baseline workflow for Kinocut."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from kinocut import Client
from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import ProcessingError


WORKFLOW_DIR = Path(__file__).resolve().parent
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


def _generate_source(path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )


def main() -> None:
    print("=" * 60)
    print("05-confidence-baseline workflow")
    print("=" * 60)

    client = Client()
    source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else OUTPUT_DIR / "source.mp4"

    tool_calls: list[dict[str, str | None]] = []

    if not source.exists():
        print("\n[0/7] Generating synthetic source clip...")
        _generate_source(source)
        print(f"   -> {source}")

    info = client.info(str(source))
    duration = float(_value(info, "duration", 0) or 0)
    trim_duration = min(6.0, duration) if duration else 4.0

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
        text="MCP video proof",
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

    print("\n[6/7] Running quality and release checkpoint...")
    quality = client.quality_check(final_path)
    checkpoint = client.release_checkpoint(
        final_path, output_dir=str(OUTPUT_DIR / "checkpoint"), min_score=50, frame_count=4
    )
    tool_calls.append(
        {"stage": "06-quality", "tool": "Client.quality_check", "output": str(OUTPUT_DIR / "quality.json")}
    )
    tool_calls.append(
        {"stage": "06-checkpoint", "tool": "Client.release_checkpoint", "output": str(OUTPUT_DIR / "checkpoint")}
    )

    quality_json = quality if isinstance(quality, dict) else quality.model_dump()
    checkpoint_json = checkpoint if isinstance(checkpoint, dict) else checkpoint.model_dump()
    (OUTPUT_DIR / "quality.json").write_text(
        json.dumps(quality_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "release_checkpoint.json").write_text(
        json.dumps(checkpoint_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "user_intent": "Prove Kinocut can produce a checked vertical video from generated or local source media.",
        "source_media": {
            "path": str(source),
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
        "guardrails_triggered": quality_json.get("recommendations", []),
        "quality": {
            "all_passed": quality_json.get("all_passed"),
            "overall_score": quality_json.get("overall_score"),
            "recommendations": quality_json.get("recommendations", []),
        },
        "review_artifacts": {
            "final_video": final_path,
            "quality_report": str(OUTPUT_DIR / "quality.json"),
            "release_checkpoint": str(OUTPUT_DIR / "release_checkpoint.json"),
            "thumbnail": checkpoint_json.get("thumbnail"),
            "storyboard": checkpoint_json.get("storyboard", {}).get("frames", []),
        },
        "human_review": {
            "required": True,
            "status": "pending",
            "instructions": checkpoint_json.get(
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

    print("\n[7/7] Writing Video Receipt...")
    receipt_path = OUTPUT_DIR / "video_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"   -> {receipt_path}")

    print("\n" + "=" * 60)
    print("Confidence baseline complete. Human review is still required.")
    print("=" * 60)


if __name__ == "__main__":
    main()
