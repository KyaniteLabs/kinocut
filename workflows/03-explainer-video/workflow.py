#!/usr/bin/env python3
"""
Explainer Video Workflow for mcp-video.

Builds a branded explainer video from scratch using synthesized audio, scenes,
effects, and transitions — using only mcp-video client methods.

Usage:
    python workflow.py

The script runs 9 stages and outputs the final video plus a Video Receipt.
"""

import json
import os
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise ImportError("Pillow is required for the explainer workflow. Install it with: pip install Pillow") from exc

from mcp_video import Client

client = Client()

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TMP_DIR = os.path.join(OUTPUT_DIR, "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

SCENES = [
    {"color": "#1a1a2e", "text": "Meet mcp-video", "duration": 5},
    {"color": "#16213e", "text": "Edit video with AI agents", "duration": 5},
    {"color": "#0f3460", "text": "87 MCP tools at your command", "duration": 5},
    {"color": "#533483", "text": "FFmpeg edits + Hyperframes creation", "duration": 5},
]

FPS = 30
WIDTH, HEIGHT = 1920, 1080


def _value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _dump_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def _load_font(size: int):
    """Try common system fonts across platforms, fallback to default."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "C:/Windows/Fonts/arial.ttf",  # Windows
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _create_scene_image(color: str, text: str, output: str) -> str:
    """Create a branded scene image using Pillow."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(img)
    font = _load_font(64)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (WIDTH - text_w) // 2
    y = (HEIGHT - text_h) // 2
    draw.rectangle(
        [x - 20, y - 10, x + text_w + 20, y + text_h + 10],
        fill="black",
    )
    draw.text((x, y), text, fill="white", font=font)
    img.save(output)
    return output


def _stage_soundtrack() -> str:
    print("\n[1/9] Generating soundtrack...")
    drone = client.audio_preset(
        "drone-tech",
        os.path.join(TMP_DIR, "drone.wav"),
        duration=20,
        intensity=0.4,
    )
    chime = client.audio_preset(
        "chime-success",
        os.path.join(TMP_DIR, "chime.wav"),
        intensity=0.6,
    )
    soundtrack = client.audio_compose(
        tracks=[
            {"file": drone.output_path, "volume": 0.3, "start": 0},
            {"file": chime.output_path, "volume": 0.8, "start": 0},
            {"file": chime.output_path, "volume": 0.8, "start": 5},
            {"file": chime.output_path, "volume": 0.8, "start": 10},
            {"file": chime.output_path, "volume": 0.8, "start": 15},
        ],
        duration=20,
        output=os.path.join(OUTPUT_DIR, "01_soundtrack.wav"),
    )
    print(f"   -> {soundtrack.output_path}")
    return soundtrack.output_path


def _stage_scenes() -> list[str]:
    print("\n[2/9] Creating scene videos...")
    scene_clips = []
    for i, scene in enumerate(SCENES):
        img_path = os.path.join(TMP_DIR, f"scene_{i:02d}.png")
        _create_scene_image(scene["color"], scene["text"], img_path)
        frame_count = int(scene["duration"] * FPS)
        images = [img_path] * frame_count
        video_path = os.path.join(TMP_DIR, f"scene_{i:02d}.mp4")
        result = client.create_from_images(images, output=video_path, fps=FPS)
        scene_clips.append(result.output_path)
        print(f"   -> {result.output_path}")
    return scene_clips


def _stage_effects(scene_clips: list[str]) -> list[str]:
    print("\n[3/9] Applying effects...")
    fx_clips = []
    for i, clip in enumerate(scene_clips):
        out = os.path.join(TMP_DIR, f"scene_{i:02d}_fx.mp4")
        if i % 2 == 0:
            client.effect_vignette(clip, out, intensity=0.4)
        else:
            client.effect_glow(clip, out, intensity=0.3)
        fx_clips.append(out)
        print(f"   -> {out}")
    return fx_clips


def _stage_transitions(fx_clips: list[str]) -> list[str]:
    print("\n[4/9] Creating transitions...")
    transition_clips = []
    for i in range(len(fx_clips) - 1):
        out = os.path.join(TMP_DIR, f"transition_{i:02d}.mp4")
        if i % 3 == 0:
            client.transition_glitch(fx_clips[i], fx_clips[i + 1], out, duration=0.5)
        elif i % 3 == 1:
            client.transition_pixelate(fx_clips[i], fx_clips[i + 1], out, duration=0.5)
        else:
            client.transition_morph(fx_clips[i], fx_clips[i + 1], out, duration=0.5)
        transition_clips.append(out)
        print(f"   -> {out}")
    return transition_clips


def _stage_assemble(fx_clips: list[str]) -> str:
    print("\n[5/9] Assembling scenes with transitions...")
    assembled = client.merge(
        clips=fx_clips,
        output=os.path.join(OUTPUT_DIR, "05_assembled.mp4"),
        transitions=["fade", "wiperight", "dissolve"],
        transition_duration=0.5,
    )
    print(f"   -> {assembled.output_path}")
    return assembled.output_path


def _stage_audio_mix(video: str, soundtrack: str) -> str:
    print("\n[6/9] Mixing audio...")
    mixed = client.add_audio(
        video=video,
        audio=soundtrack,
        mix=True,
        volume=0.8,
        output=os.path.join(OUTPUT_DIR, "06_mixed.mp4"),
    )
    print(f"   -> {mixed.output_path}")
    return mixed.output_path


def _stage_export(video: str) -> str:
    print("\n[7/9] Exporting final video...")
    final = client.convert(
        video,
        format="mp4",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "final_video.mp4"),
    )
    print(f"   -> {final.output_path}")
    return final.output_path


def _stage_quality_checkpoint(video: str) -> tuple[dict[str, Any], dict[str, Any]]:
    print("\n[8/9] Running quality and release checkpoint...")
    quality = client.quality_check(video)
    checkpoint = client.release_checkpoint(
        video,
        output_dir=os.path.join(OUTPUT_DIR, "checkpoint"),
        min_score=0,
        frame_count=4,
    )
    quality_json = quality if isinstance(quality, dict) else quality.model_dump()
    checkpoint_json = checkpoint if isinstance(checkpoint, dict) else checkpoint.model_dump()
    _dump_json(os.path.join(OUTPUT_DIR, "quality.json"), quality_json)
    _dump_json(os.path.join(OUTPUT_DIR, "release_checkpoint.json"), checkpoint_json)
    print(f"   -> {os.path.join(OUTPUT_DIR, 'quality.json')}")
    print(f"   -> {os.path.join(OUTPUT_DIR, 'release_checkpoint.json')}")
    return quality_json, checkpoint_json


def _write_receipt(
    soundtrack: str,
    scene_clips: list[str],
    fx_clips: list[str],
    assembled: str,
    mixed: str,
    final_video: str,
    quality: dict[str, Any],
    checkpoint: dict[str, Any],
) -> None:
    print("\n[9/9] Writing Video Receipt...")
    info = client.info(final_video)
    receipt = {
        "user_intent": "Build a branded explainer video from generated scenes, procedural audio, effects, and transitions.",
        "source_media": {
            "path": "generated-from-scenes",
            "duration_seconds": _value(info, "duration"),
            "width": _value(info, "width"),
            "height": _value(info, "height"),
        },
        "tool_calls": [
            {"stage": "01-audio", "tool": "Client.audio_preset + Client.audio_compose", "output": soundtrack},
            {"stage": "02-scenes", "tool": "Client.create_from_images", "output": ", ".join(scene_clips)},
            {"stage": "03-effects", "tool": "Client.effect_vignette / Client.effect_glow", "output": ", ".join(fx_clips)},
            {"stage": "05-assemble", "tool": "Client.merge", "output": assembled},
            {"stage": "06-audio-mix", "tool": "Client.add_audio", "output": mixed},
            {"stage": "07-export", "tool": "Client.convert", "output": final_video},
            {"stage": "08-quality", "tool": "Client.quality_check", "output": os.path.join(OUTPUT_DIR, "quality.json")},
            {
                "stage": "08-checkpoint",
                "tool": "Client.release_checkpoint",
                "output": os.path.join(OUTPUT_DIR, "checkpoint"),
            },
        ],
        "edits_applied": [
            "generated soundtrack",
            "created title-card scene clips",
            "applied visual effects",
            "assembled scenes",
            "mixed procedural audio",
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
            "final_video": final_video,
            "quality_report": os.path.join(OUTPUT_DIR, "quality.json"),
            "release_checkpoint": os.path.join(OUTPUT_DIR, "release_checkpoint.json"),
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
            "Generated title cards prove workflow plumbing, not final brand taste.",
            "Automated quality checks do not replace visual/audio review.",
        ],
        "next_edit_suggestion": "Review title-card pacing, visual style, and audio mix before using this as a public demo.",
    }
    receipt_path = os.path.join(OUTPUT_DIR, "video_receipt.json")
    _dump_json(receipt_path, receipt)
    print(f"   -> {receipt_path}")


def main() -> None:
    print("=" * 60)
    print("03-explainer-video workflow")
    print("=" * 60)

    soundtrack = _stage_soundtrack()
    scene_clips = _stage_scenes()
    fx_clips = _stage_effects(scene_clips)
    _stage_transitions(fx_clips)
    assembled = _stage_assemble(fx_clips)
    mixed = _stage_audio_mix(assembled, soundtrack)
    final_video = _stage_export(mixed)
    quality, checkpoint = _stage_quality_checkpoint(final_video)
    _write_receipt(soundtrack, scene_clips, fx_clips, assembled, mixed, final_video, quality, checkpoint)

    print("\n" + "=" * 60)
    print("Workflow complete! Review output/final_video.mp4 and output/video_receipt.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
