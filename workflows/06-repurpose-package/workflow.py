#!/usr/bin/env python3
"""Golden repurposing package workflow for Kinocut."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from kinocut import Client
from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import ProcessingError
from kinocut.ffmpeg_helpers import _validate_input_path


WORKFLOW_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = WORKFLOW_DIR / "output"
PACKAGE_DIR = OUTPUT_DIR / "package"
OUTPUT_DIR.mkdir(exist_ok=True)

PLATFORMS = ["youtube-shorts", "instagram-post"]


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


def _variant_review_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    variants = []
    for variant in manifest.get("variants", []):
        checkpoint = variant.get("release_checkpoint", {})
        storyboard = variant.get("storyboard", {})
        variants.append(
            {
                "platform": variant.get("platform"),
                "output_video": variant.get("output_path"),
                "thumbnail": variant.get("thumbnail"),
                "storyboard": storyboard.get("frames", []) if isinstance(storyboard, dict) else storyboard,
                "release_checkpoint": checkpoint,
                "quality": checkpoint.get("quality", {}) if isinstance(checkpoint, dict) else {},
            }
        )
    return variants


def _quality_summary(variants: list[dict[str, Any]]) -> dict[str, Any]:
    scores = []
    recommendations = []
    for variant in variants:
        quality = variant.get("quality", {})
        score = quality.get("overall_score") if isinstance(quality, dict) else None
        if score is not None:
            scores.append(score)
        recommendations.extend(quality.get("recommendations", []) if isinstance(quality, dict) else [])
    return {
        "all_passed": not recommendations,
        "overall_score": min(scores) if scores else None,
        "recommendations": recommendations,
    }


def main() -> None:
    print("=" * 60)
    print("06-repurpose-package workflow")
    print("=" * 60)

    client = Client()
    source = Path(_validate_input_path(sys.argv[1])) if len(sys.argv) > 1 else OUTPUT_DIR / "source.mp4"

    if not source.exists():
        print("\n[1/5] Generating synthetic source clip...")
        _generate_source(source)
        print(f"   -> {source}")
    else:
        print("\n[1/5] Using source clip...")
        print(f"   -> {source}")

    print("\n[2/5] Inspecting source...")
    info = client.info(str(source))
    print(f"   -> {_value(info, 'display_resolution')} / {_value(info, 'duration')}s")

    print("\n[3/5] Creating repurposing package...")
    manifest = client.repurpose(
        str(source),
        output_dir=str(PACKAGE_DIR),
        platforms=PLATFORMS,
        include_release_checkpoint=True,
        min_score=50,
    )
    manifest_path = manifest.get("manifest_path", str(PACKAGE_DIR / "repurpose_manifest.json"))
    print(f"   -> {manifest_path}")

    print("\n[4/5] Collecting review artifacts...")
    variant_artifacts = _variant_review_artifacts(manifest)
    quality = _quality_summary(variant_artifacts)
    print(f"   -> {len(variant_artifacts)} variants")

    print("\n[5/5] Writing Video Receipt...")
    receipt = {
        "user_intent": "Create a local platform-ready repurposing package from one source video.",
        "source_media": {
            "path": str(source),
            "duration_seconds": _value(info, "duration"),
            "width": _value(info, "width"),
            "height": _value(info, "height"),
        },
        "tool_calls": [
            {"stage": "02-inspect", "tool": "Client.info", "output": None},
            {"stage": "03-repurpose", "tool": "Client.repurpose", "output": manifest_path},
        ],
        "edits_applied": [
            "created platform-specific variants",
            "normalized platform audio",
            "exported package videos",
            "created thumbnails",
            "created storyboards",
            "created release checkpoints",
        ],
        "guardrails_triggered": quality["recommendations"],
        "quality": quality,
        "review_artifacts": {
            "manifest": manifest_path,
            "variants": variant_artifacts,
        },
        "human_review": {
            "required": True,
            "status": "pending",
            "instructions": "Open each variant, thumbnail, storyboard, and checkpoint before publishing.",
        },
        "known_limitations": [
            "Synthetic source media proves repurposing plumbing, not creative quality.",
            "Platform packaging does not replace human review of crop, caption, and brand fit.",
        ],
        "next_edit_suggestion": "Review each platform variant and adjust crop, captions, or loudness targets before publishing.",
    }
    receipt_path = OUTPUT_DIR / "video_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"   -> {receipt_path}")

    print("\n" + "=" * 60)
    print("Repurpose package complete. Human review is still required.")
    print("=" * 60)


if __name__ == "__main__":
    main()
