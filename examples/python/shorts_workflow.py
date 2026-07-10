#!/usr/bin/env python3
"""
YouTube Shorts Workflow Example for Kinocut.

Demonstrates how to use the Kinocut Python client to create a YouTube Short
from a longer video. The workflow:
  1. Trim a highlight clip
  2. Resize to 9:16 vertical format
  3. Add animated captions
  4. Normalize audio for social media
  5. Export the final short

Requirements:
  - kinocut Python client installed

Usage:
  python3 shorts_workflow.py

Replace placeholder paths with your actual file paths before running.
"""

import os

from kinocut import Client

# ---------------------------------------------------------------------------
# Configuration -- replace these with your actual paths and preferences
# ---------------------------------------------------------------------------
INPUT_VIDEO = "/videos/my_long_video.mp4"
OUTPUT_DIR = "/output"
CLIP_START = "2:15"  # Timestamp where the highlight begins
CLIP_DURATION = "45"  # Duration in seconds (YouTube Shorts max: 60s)
CAPTION_TEXT = "This changes everything."
CAPTION_START = 2.0  # Seconds into the clip to show caption
CAPTION_DURATION = 5.0  # How long the caption stays on screen
LOGO_PATH = "/assets/logo.png"
TARGET_LUFS = -14  # Target loudness for TikTok/Shorts (-14 LUFS)


def main() -> None:
    client = Client()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Trim the highlight segment from the longer video.
    # We extract a 45-second clip starting at the 2:15 mark.
    # Keeping Shorts under 60 seconds maximizes completion rate.
    # ------------------------------------------------------------------
    print("[1/5] Trimming highlight segment...")
    trimmed = client.trim(
        INPUT_VIDEO,
        start=CLIP_START,
        duration=CLIP_DURATION,
        output=os.path.join(OUTPUT_DIR, "short_trimmed.mp4"),
    )
    print(f"   -> {trimmed.output_path}")

    # ------------------------------------------------------------------
    # Step 2: Resize to 9:16 vertical format for Shorts.
    # YouTube Shorts require a vertical aspect ratio. The tool handles
    # center-cropping to keep the subject in frame.
    # ------------------------------------------------------------------
    print("[2/5] Resizing to 9:16 vertical format...")
    resized = client.resize(
        trimmed.output_path,
        aspect_ratio="9:16",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "short_vertical.mp4"),
    )
    print(f"   -> {resized.output_path}")

    # ------------------------------------------------------------------
    # Step 3: Add animated caption overlay.
    # Bold animated text in the center of the screen is the standard
    # Shorts pattern. The typewriter animation draws the eye.
    # ------------------------------------------------------------------
    print("[3/5] Adding animated caption...")
    captioned = client.text_animated(
        resized.output_path,
        text=CAPTION_TEXT,
        animation="typewriter",
        font="Arial Black",
        size=42,
        color="#FFFFFF",
        position="center",
        start=CAPTION_START,
        duration=CAPTION_DURATION,
        output=os.path.join(OUTPUT_DIR, "short_captioned.mp4"),
    )
    print(f"   -> {captioned.output_path}")

    # ------------------------------------------------------------------
    # Step 4: Normalize audio levels.
    # Social platforms apply their own loudness normalization. Setting
    # to -14 LUFS ensures your audio does not get crushed or seem too
    # quiet after platform processing.
    # ------------------------------------------------------------------
    print("[4/5] Normalizing audio to -14 LUFS...")
    normalized = client.normalize_audio(
        captioned.output_path,
        target_lufs=TARGET_LUFS,
        output=os.path.join(OUTPUT_DIR, "short_normalized.mp4"),
    )
    print(f"   -> {normalized.output_path}")

    # ------------------------------------------------------------------
    # Step 5: Export the final video.
    # High quality MP4 is the safest format for upload to YouTube,
    # TikTok, and Instagram Reels.
    # ------------------------------------------------------------------
    print("[5/5] Exporting final Short...")
    final = client.export(
        normalized.output_path,
        format="mp4",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "youtube_short_final.mp4"),
    )
    print(f"   -> {final.output_path}")

    # ------------------------------------------------------------------
    # Bonus: Run a quality check on the final output.
    # Catches issues like audio clipping, low contrast, or dim brightness
    # before you upload. Fix with video_fix_design_issues if needed.
    # ------------------------------------------------------------------
    print("[bonus] Running quality check...")
    qc = client.quality_check(final.output_path)
    if qc.get("all_passed"):
        print("   -> Quality check PASSED. Ready to upload!")
    else:
        print(f"   -> Quality issues found: {qc.get('recommendations', [])}")
        print("   -> Consider running video_fix_design_issues to auto-correct.")

    print("\nDone! Upload youtube_short_final.mp4 to YouTube Shorts.")


if __name__ == "__main__":
    main()
