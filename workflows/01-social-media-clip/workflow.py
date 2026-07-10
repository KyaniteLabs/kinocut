#!/usr/bin/env python3
"""
Social Media Clip Workflow for Kinocut.

Turns landscape video into a vertical TikTok / Short / Reel.

Usage:
    python workflow.py /path/to/raw_video.mp4

The script runs 5 stages and outputs the final clip to output/final_clip.mp4.
"""

import os
import sys

from kinocut import Client

client = Client()

INPUT_VIDEO = sys.argv[1] if len(sys.argv) > 1 else input("Path to raw video: ").strip()
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def main() -> None:
    print("=" * 60)
    print("01-social-media-clip workflow")
    print("=" * 60)

    # Stage 1: Trim the viral moment
    print("\n[1/5] Trimming highlight segment...")
    info = client.info(INPUT_VIDEO)
    duration = info.duration
    # Trim to the middle 30 seconds, or the whole video if shorter
    start = max(0, (duration - 30) / 2)
    clip_duration = min(30, duration)
    trimmed = client.trim(
        INPUT_VIDEO,
        start=f"{int(start // 60):02d}:{int(start % 60):02d}",
        duration=f"{int(clip_duration)}",
        output=os.path.join(OUTPUT_DIR, "01_trimmed.mp4"),
    )
    print(f"   -> {trimmed.output_path} ({clip_duration:.1f}s)")

    # Stage 2: Resize to 9:16
    print("\n[2/5] Resizing to 9:16 vertical format...")
    vertical = client.resize(
        trimmed.output_path,
        aspect_ratio="9:16",
        output=os.path.join(OUTPUT_DIR, "02_vertical.mp4"),
    )
    print(f"   -> {vertical.output_path}")

    # Stage 3: Add hook text
    print("\n[3/5] Adding hook text...")
    hooked = client.add_text(
        vertical.output_path,
        text="Wait for it...",
        position="top-center",
        size=36,
        color="#CCFF00",
        start_time=0,
        duration=3,
        output=os.path.join(OUTPUT_DIR, "03_captioned.mp4"),
    )
    print(f"   -> {hooked.output_path}")

    # Stage 4: Normalize audio
    print("\n[4/5] Normalizing audio to -14 LUFS...")
    normalized = client.normalize_audio(
        hooked.output_path,
        target_lufs=-14.0,
        output=os.path.join(OUTPUT_DIR, "04_normalized.mp4"),
    )
    print(f"   -> {normalized.output_path}")

    # Stage 5: Export final
    print("\n[5/5] Exporting final clip...")
    final = client.convert(
        normalized.output_path,
        format="mp4",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "final_clip.mp4"),
    )
    print(f"   -> {final.output_path}")

    print("\n" + "=" * 60)
    print("Workflow complete! Upload output/final_clip.mp4")
    print("=" * 60)


if __name__ == "__main__":
    main()
