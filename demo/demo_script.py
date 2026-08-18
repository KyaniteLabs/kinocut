"""
Kinocut Live Demo Script
========================
Run this to demonstrate Kinocut's capabilities (formerly mcp-video).
Requires: a video file (mp4), FFmpeg with drawtext support.

Usage:
    python demo/demo_script.py path/to/video.mp4

The script chains multiple operations and prints results at each step.
"""

import os
import sys
import time
from pathlib import Path

# Add parent to path so we can import mcp_video
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_video import Client


def divider(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def step(n: int, description: str):
    print(f"[Step {n}] {description}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo/demo_script.py <video_path>")
        print("Example: python demo/demo_script.py ~/Videos/interview.mp4")
        sys.exit(1)

    video = sys.argv[1]
    if not os.path.isfile(video):
        print(f"Error: {video} not found")
        sys.exit(1)

    editor = Client()
    total_start = time.time()

    # ─── Step 1: Info ─────────────────────────────────────────────
    divider("VIDEO INFO")
    step(1, "Analyzing video metadata...")
    info = editor.info(video)
    print(f"  File:     {os.path.basename(video)}")
    print(f"  Duration: {info.duration:.1f}s")
    print(f"  Resolution: {info.resolution} ({info.aspect_ratio})")
    print(f"  Codec:    {info.codec} / {info.audio_codec or 'no audio'}")
    print(f"  FPS:      {info.fps}")
    print(f"  Size:     {info.size_mb:.2f} MB")

    # ─── Step 2: Trim ──────────────────────────────────────────────
    divider("TRIM")
    # Use middle 30% of the video for a good demo
    trim_start = info.duration * 0.2
    trim_duration = min(info.duration * 0.3, 30)  # Cap at 30s
    step(2, f"Trimming from {trim_start:.1f}s for {trim_duration:.1f}s...")
    trimmed = editor.trim(video, start=str(trim_start), duration=str(trim_duration))
    print(f"  Output: {os.path.basename(trimmed.output_path)}")
    print(f"  Duration: {trimmed.duration:.1f}s")

    # ─── Step 3: Preview ───────────────────────────────────────────
    divider("PREVIEW")
    step(3, "Generating fast low-res preview...")
    preview = editor.preview(trimmed.output_path, scale_factor=4)
    prev_info = editor.info(preview.output_path)
    print(f"  Output: {os.path.basename(preview.output_path)}")
    print(f"  Resolution: {prev_info.resolution} (downscaled)")

    # ─── Step 4: Storyboard ────────────────────────────────────────
    divider("STORYBOARD")
    step(4, "Extracting key frames for review...")
    sb = editor.storyboard(trimmed.output_path, frame_count=6)
    print(f"  Frames: {sb.count}")
    for f in sb.frames:
        print(f"    {os.path.basename(f)}")
    if sb.grid:
        print(f"  Grid: {os.path.basename(sb.grid)}")

    # ─── Step 5: Thumbnail ─────────────────────────────────────────
    divider("THUMBNAIL")
    step(5, "Extracting thumbnail at 50%...")
    thumb_ts = trimmed.duration * 0.5
    thumb = editor.thumbnail(trimmed.output_path, timestamp=thumb_ts)
    print(f"  Output: {os.path.basename(thumb.frame_path)}")
    print(f"  Timestamp: {thumb.timestamp:.1f}s")

    # ─── Step 6: Add text ──────────────────────────────────────────
    divider("TEXT OVERLAY")
    step(6, "Adding title card...")
    try:
        titled = editor.add_text(
            trimmed.output_path,
            text="MCP-VIDEO DEMO",
            position="top-center",
            size=48,
            color="white",
            start_time=0,
            duration=min(3, trimmed.duration),
        )
        print(f"  Output: {os.path.basename(titled.output_path)}")
        current = titled.output_path
    except Exception as e:
        print(f"  Skipped (drawtext filter not available): {e}")
        current = trimmed.output_path

    # ─── Step 7: Speed change ──────────────────────────────────────
    divider("SPEED")
    step(7, "Creating slow-motion version (0.5x)...")
    slow = editor.speed(current, factor=0.5)
    slow_info = editor.info(slow.output_path)
    print(f"  Output: {os.path.basename(slow.output_path)}")
    print(f"  Duration: {slow_info.duration:.1f}s (from {trimmed.duration:.1f}s)")

    # ─── Step 8: Convert ───────────────────────────────────────────
    divider("FORMAT CONVERSION")
    step(8, "Converting to WebM...")
    webm = editor.convert(trimmed.output_path, format="webm", quality="medium")
    webm_size = os.path.getsize(webm.output_path) / (1024 * 1024)
    print(f"  Output: {os.path.basename(webm.output_path)}")
    print(f"  Size: {webm_size:.2f} MB")

    step(9, "Converting to GIF...")
    gif = editor.convert(trimmed.output_path, format="gif", quality="low")
    gif_size = os.path.getsize(gif.output_path) / (1024 * 1024)
    print(f"  Output: {os.path.basename(gif.output_path)}")
    print(f"  Size: {gif_size:.2f} MB")

    # ─── Step 10: Resize for social ────────────────────────────────
    divider("RESIZE FOR PLATFORMS")
    step(10, "Resizing for TikTok (9:16)...")
    tiktok = editor.resize(trimmed.output_path, aspect_ratio="9:16")
    tk_info = editor.info(tiktok.output_path)
    print(f"  Output: {os.path.basename(tiktok.output_path)}")
    print(f"  Resolution: {tk_info.resolution}")

    step(11, "Resizing for YouTube (16:9)...")
    youtube = editor.resize(trimmed.output_path, aspect_ratio="16:9")
    yt_info = editor.info(youtube.output_path)
    print(f"  Output: {os.path.basename(youtube.output_path)}")
    print(f"  Resolution: {yt_info.resolution}")

    step(12, "Resizing for Instagram (1:1)...")
    insta = editor.resize(trimmed.output_path, aspect_ratio="1:1")
    ig_info = editor.info(insta.output_path)
    print(f"  Output: {os.path.basename(insta.output_path)}")
    print(f"  Resolution: {ig_info.resolution}")

    # ─── Step 11: Extract audio ────────────────────────────────────
    divider("AUDIO EXTRACTION")
    step(13, "Extracting audio as MP3...")
    mp3_size = 0
    try:
        mp3 = editor.extract_audio(trimmed.output_path, format="mp3")
        mp3_size = os.path.getsize(mp3) / (1024 * 1024)
        print(f"  Output: {os.path.basename(mp3)}")
        print(f"  Size: {mp3_size:.2f} MB")
    except Exception as e:
        print(f"  Skipped (no audio track): {e}")

    # ─── Step 12: Template workflow ────────────────────────────────
    divider("TEMPLATE WORKFLOW")
    step(14, "Using TikTok template...")
    from mcp_video.templates import tiktok_template

    timeline = tiktok_template(trimmed.output_path, caption="Built with Kinocut")
    print("  Template: TikTok (1080x1920)")
    print(f"  Tracks: {len(timeline['tracks'])} ({', '.join(t['type'] for t in timeline['tracks'])})")
    print(f"  Export: {timeline['export']['format']} / {timeline['export']['quality']}")

    try:
        result = editor.edit(timeline)
        print(f"  Output: {os.path.basename(result.output_path)}")
    except Exception as e:
        print(f"  Skipped (requires drawtext filter): {e}")

    # ─── Summary ──────────────────────────────────────────────────
    total_time = time.time() - total_start
    divider("SUMMARY")
    print("  Operations completed: 14")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Input:  {os.path.basename(video)}")
    print("  Outputs:")
    print(f"    Trimmed clip ({trimmed.resolution})")
    print(f"    Preview ({prev_info.resolution})")
    print(f"    Storyboard ({sb.count} frames)")
    print("    Thumbnail")
    print(f"    Slow-mo (0.5x, {slow_info.duration:.1f}s)")
    print(f"    WebM ({webm_size:.1f} MB)")
    print(f"    GIF ({gif_size:.1f} MB)")
    print(f"    TikTok ({tk_info.resolution})")
    print(f"    YouTube ({yt_info.resolution})")
    print(f"    Instagram ({ig_info.resolution})")
    if mp3_size:
        print(f"    MP3 ({mp3_size:.1f} MB)")
    print(f"\n  All outputs saved in: {os.path.dirname(trimmed.output_path)}")


if __name__ == "__main__":
    main()
