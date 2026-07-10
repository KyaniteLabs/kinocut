#!/usr/bin/env python3
"""Agent cookbook for a guarded Kinocut render pipeline.

This is intentionally copy/paste friendly:
1. Inspect the real client signature before calling a tool.
2. Create a video from image frames.
3. Apply a conservative effect.
4. Add audio.
5. Export.
6. Run a hard quality/review checkpoint before publishing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kinocut import Client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kinocut agent cookbook")
    parser.add_argument("--frames-dir", default="frames", help="Directory of image frames")
    parser.add_argument("--audio", default="soundtrack.wav", help="Audio file to add")
    parser.add_argument("--output", default="final.mp4", help="Final output video")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned calls without touching media")
    return parser.parse_args()


def discover_frames(frames_dir: str) -> list[str]:
    frames = sorted(
        str(path) for path in Path(frames_dir).glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not frames:
        raise SystemExit(f"No frames found in {frames_dir}; expected PNG/JPG images.")
    return frames


def main() -> int:
    args = parse_args()
    client = Client()
    steps = [
        {"op": "create_from_images", "images": ["frame_001.png", "frame_002.png"], "output_path": "scene.mp4"},
        {"op": "effect_glow", "intensity": 0.2},
        {"op": "add_audio", "audio": args.audio},
        {"op": "export", "quality": "high", "format": "mp4"},
    ]

    if args.dry_run:
        print("Inspect create_from_images:", client.inspect("create_from_images"))
        print("Pipeline steps:")
        for step in steps:
            print(" -", step)
        print("After rendering, run: client.assert_quality(output_path) or video_release_checkpoint.")
        return 0

    frames = discover_frames(args.frames_dir)
    steps[0]["images"] = frames
    result = client.pipeline(steps, output_path=args.output)
    client.assert_quality(result.output_path)
    print(f"Rendered guarded output: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
