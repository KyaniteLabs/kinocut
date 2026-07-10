#!/usr/bin/env python3
"""
Podcast Clip Workflow for Kinocut.

Extracts a highlight from a podcast episode with auto-chapters and burned captions.

Usage:
    python workflow.py /path/to/episode.mp4

The script runs 6 stages and outputs the final clip to output/final_clip.mp4.
"""

import json
import os
import sys

from kinocut import Client

client = Client()

INPUT_VIDEO = sys.argv[1] if len(sys.argv) > 1 else input("Path to episode: ").strip()
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _save_scenes(scenes_result, path: str) -> None:
    data = scenes_result.model_dump() if hasattr(scenes_result, "model_dump") else scenes_result
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _save_chapters(chapters, path: str) -> None:
    if isinstance(chapters, dict):
        chapters = chapters.get("chapters", chapters.get("data", []))
    with open(path, "w") as f:
        json.dump([{"time": t, "title": title} for t, title in chapters], f, indent=2)


def _stage_detect(video: str) -> str:
    print("\n[1/6] Detecting scenes...")
    scenes = client.detect_scenes(video, threshold=0.3)
    path = os.path.join(OUTPUT_DIR, "01_scenes.json")
    _save_scenes(scenes, path)
    scene_count = getattr(scenes, "scene_count", None)
    if scene_count is None and isinstance(scenes, dict):
        scene_count = scenes.get("scene_count", len(scenes.get("scenes", [])))
    print(f"   -> {path} ({scene_count} scenes)")
    return path


def _stage_chapters(video: str) -> str:
    print("\n[2/6] Generating chapter markers...")
    chapters = client.auto_chapters(video, threshold=0.3)
    path = os.path.join(OUTPUT_DIR, "02_chapters.json")
    _save_chapters(chapters, path)
    print(f"   -> {path} ({len(chapters)} chapters)")
    return path


def _stage_trim(video: str) -> str:
    print("\n[3/6] Trimming highlight segment...")
    info = client.info(video)
    start = 30
    clip_duration = min(60, max(30, info.duration - start))
    trimmed = client.trim(
        video,
        start=f"{int(start // 60):02d}:{int(start % 60):02d}",
        duration=f"{int(clip_duration)}",
        output=os.path.join(OUTPUT_DIR, "03_highlight.mp4"),
    )
    print(f"   -> {trimmed.output_path} ({clip_duration:.1f}s)")
    return trimmed.output_path


def _stage_transcribe(video: str) -> str:
    print("\n[4/6] Transcribing audio...")
    srt_path = os.path.join(OUTPUT_DIR, "04_transcript.srt")
    result = client.ai_transcribe(video, output_srt=srt_path)
    segments = result.get("segments", []) if isinstance(result, dict) else getattr(result, "segments", [])
    print(f"   -> {srt_path} ({len(segments)} segments)")
    return srt_path


def _stage_captions(video: str, srt_path: str) -> str:
    print("\n[5/6] Burning captions into video...")
    captioned = client.subtitles_styled(
        video,
        subtitles=srt_path,
        output=os.path.join(OUTPUT_DIR, "05_captioned.mp4"),
        style={"font_size": 32, "font_color": "white", "outline": True},
    )
    print(f"   -> {captioned.output_path}")
    return captioned.output_path


def _stage_export(video: str) -> str:
    print("\n[6/6] Exporting final clip...")
    final = client.convert(
        video,
        format="mp4",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "final_clip.mp4"),
    )
    print(f"   -> {final.output_path}")
    return final.output_path


def main() -> None:
    print("=" * 60)
    print("02-podcast-clip workflow")
    print("=" * 60)

    _stage_detect(INPUT_VIDEO)
    _stage_chapters(INPUT_VIDEO)
    highlight = _stage_trim(INPUT_VIDEO)
    srt = _stage_transcribe(highlight)
    captioned = _stage_captions(highlight, srt)
    _stage_export(captioned)

    print("\n" + "=" * 60)
    print("Workflow complete! Upload output/final_clip.mp4")
    print("=" * 60)


if __name__ == "__main__":
    main()
