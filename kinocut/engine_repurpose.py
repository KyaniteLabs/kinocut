"""Content repurposing orchestration for platform-ready video packages."""

from __future__ import annotations

import json
import os
from typing import Any

from .engine_audio_normalize import normalize_audio
from .engine_export import export_video
from .engine_probe import probe
from .engine_resize import resize
from .engine_storyboard import storyboard
from .engine_thumbnail import thumbnail
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .paths import _auto_output_dir
from .quality_guardrails import assert_quality


PLATFORM_PRESETS: dict[str, dict[str, Any]] = {
    "youtube": {
        "aspect_ratio": "16:9",
        "width": 1920,
        "height": 1080,
        "target_lufs": -16.0,
        "max_duration": None,
        "hyperframes_blocks": ["yt-lower-third", "logo-outro"],
    },
    "youtube-shorts": {
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "target_lufs": -14.0,
        "max_duration": 180,
        "hyperframes_blocks": ["captions-slam", "yt-lower-third"],
    },
    "tiktok": {
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "target_lufs": -14.0,
        "max_duration": 600,
        "hyperframes_blocks": ["captions-bounce", "tiktok-follow"],
    },
    "instagram-reel": {
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "target_lufs": -14.0,
        "max_duration": 90,
        "hyperframes_blocks": ["captions-karaoke", "instagram-follow"],
    },
    "instagram-post": {
        "aspect_ratio": "1:1",
        "width": 1080,
        "height": 1080,
        "target_lufs": -14.0,
        "max_duration": 60,
        "hyperframes_blocks": ["captions-minimal", "instagram-follow"],
    },
}


def _select_platforms(platforms: list[str] | None) -> list[str]:
    selected = platforms or list(PLATFORM_PRESETS)
    unknown = [platform for platform in selected if platform not in PLATFORM_PRESETS]
    if unknown:
        raise MCPVideoError(
            f"Unknown repurpose platform(s): {', '.join(unknown)}. Available: {', '.join(PLATFORM_PRESETS)}",
            error_type="validation_error",
            code="invalid_platform",
        )
    return selected


def _prepare_output_dir(input_path: str, output_dir: str | None) -> str:
    output = output_dir or _auto_output_dir(input_path, "repurposed")
    _validate_output_path(os.path.join(output, "repurpose_manifest.json"))
    os.makedirs(output, exist_ok=True)
    return output


def _variant_filename(platform: str) -> str:
    safe = platform.replace("-", "_")
    return f"{safe}.mp4"


def _write_manifest(manifest: dict[str, Any], output_dir: str) -> str:
    manifest_path = os.path.join(output_dir, "repurpose_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return manifest_path


def _build_manifest(
    input_path: str,
    output_dir: str,
    platforms: list[str],
    *,
    render: bool,
) -> dict[str, Any]:
    info = probe(input_path)
    variants: list[dict[str, Any]] = []
    for platform in platforms:
        preset = PLATFORM_PRESETS[platform]
        variants.append(
            {
                "platform": platform,
                "aspect_ratio": preset["aspect_ratio"],
                "width": preset["width"],
                "height": preset["height"],
                "target_lufs": preset["target_lufs"],
                "max_duration": preset["max_duration"],
                "hyperframes_blocks": list(preset["hyperframes_blocks"]),
                "planned_ops": ["resize", "normalize_audio", "export", "thumbnail", "storyboard"],
                "render": render,
                "output_path": os.path.join(output_dir, _variant_filename(platform)),
            }
        )
    return {
        "success": True,
        "source": {
            "path": input_path,
            "duration": info.duration,
            "resolution": info.display_resolution,
            "aspect_ratio": info.aspect_ratio,
        },
        "variants": variants,
    }


def repurpose_plan(
    input_path: str,
    output_dir: str | None = None,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Create a dry-run manifest for a local content repurposing package."""
    input_path = _validate_input_path(input_path)
    selected = _select_platforms(platforms)
    package_dir = _prepare_output_dir(input_path, output_dir)
    manifest = _build_manifest(input_path, package_dir, selected, render=False)
    manifest["manifest_path"] = _write_manifest(manifest, package_dir)
    return manifest


def _release_checkpoint(video_path: str, output_dir: str, min_score: float) -> dict[str, Any]:
    quality = assert_quality(video_path, min_score=min_score)
    review_dir = os.path.join(output_dir, "release_review")
    os.makedirs(review_dir, exist_ok=True)
    thumb = thumbnail(video_path, output_path=os.path.join(review_dir, "thumbnail.jpg"))
    board = storyboard(video_path, output_dir=os.path.join(review_dir, "storyboard"), frame_count=4)
    return {
        "quality": quality,
        "thumbnail": thumb.output_path,
        "storyboard": board.model_dump() if hasattr(board, "model_dump") else board,
        "review_required": True,
    }


def repurpose(
    input_path: str,
    output_dir: str | None = None,
    platforms: list[str] | None = None,
    include_release_checkpoint: bool = True,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Render a local content repurposing package and manifest."""
    input_path = _validate_input_path(input_path)
    selected = _select_platforms(platforms)
    package_dir = _prepare_output_dir(input_path, output_dir)
    manifest = _build_manifest(input_path, package_dir, selected, render=True)

    for variant in manifest["variants"]:
        platform_dir = os.path.join(package_dir, variant["platform"])
        os.makedirs(platform_dir, exist_ok=True)
        resized = resize(
            input_path,
            aspect_ratio=variant["aspect_ratio"],
            output_path=os.path.join(platform_dir, "01_resized.mp4"),
        )
        normalized = normalize_audio(
            resized.output_path,
            target_lufs=variant["target_lufs"],
            output_path=os.path.join(platform_dir, "02_normalized.mp4"),
        )
        exported = export_video(
            normalized.output_path,
            output_path=variant["output_path"],
            quality="high",
            format="mp4",
        )
        variant["output_path"] = exported.output_path
        variant["thumbnail"] = thumbnail(
            exported.output_path,
            output_path=os.path.join(platform_dir, "thumbnail.jpg"),
        ).output_path
        variant["storyboard"] = storyboard(
            exported.output_path,
            output_dir=os.path.join(platform_dir, "storyboard"),
            frame_count=4,
        ).model_dump()
        if include_release_checkpoint:
            variant["release_checkpoint"] = _release_checkpoint(
                exported.output_path,
                os.path.join(platform_dir, "checkpoint"),
                min_score=min_score,
            )

    manifest["manifest_path"] = _write_manifest(manifest, package_dir)
    return manifest
