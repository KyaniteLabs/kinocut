#!/usr/bin/env python3
"""
Hyperframes Video Workflow for Kinocut.

Creates a video from scratch using Hyperframes (HTML-native, Apache 2.0),
then post-processes with Kinocut client methods.

Requires: Node.js 22+ and npx

Usage:
    python workflow.py [project_name] [template]

Templates: blank, warm-grain, swiss-grid

The script runs 5 stages and outputs the final video to output/final_video.mp4.
"""

import os
import sys

from kinocut import Client

client = Client()

PROJECT_NAME = sys.argv[1] if len(sys.argv) > 1 else "my-hyperframes-video"
TEMPLATE = sys.argv[2] if len(sys.argv) > 2 else "blank"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _value(result, key: str):
    return result.get(key) if isinstance(result, dict) else getattr(result, key)


def main() -> None:
    print("=" * 60)
    print("04-hyperframes-video workflow")
    print("=" * 60)

    # Stage 1: Initialize Hyperframes project
    print("\n[1/5] Initializing Hyperframes project...")
    project = client.hyperframes_init(
        name=PROJECT_NAME,
        template=TEMPLATE,
        output_dir=OUTPUT_DIR,
    )
    project_path = _value(project, "project_path")
    print(f"   -> {project_path}")

    # Stage 2: Add blocks (optional — customize as needed)
    print("\n[2/5] Adding blocks from catalog...")
    blocks_to_add = ["text", "image"]  # Customize for your use case
    for block in blocks_to_add:
        try:
            client.hyperframes_add_block(project_path, block)
            print(f"   -> Added block: {block}")
        except Exception as e:
            print(f"   -> Skipped block '{block}': {e}")

    # Stage 3: Validate project
    print("\n[3/5] Validating project...")
    validation = client.hyperframes_validate(project_path)
    if not _value(validation, "valid"):
        print(f"   -> Validation failed: {_value(validation, 'issues')}")
        sys.exit(1)
    print("   -> Project is valid")

    # Stage 4: Render base video
    print("\n[4/5] Rendering video with Hyperframes...")
    render = client.hyperframes_render(
        project_path=project_path,
        output=os.path.join(OUTPUT_DIR, "04_render.mp4"),
        quality="high",
    )
    render_path = _value(render, "output_path")
    print(f"   -> {render_path}")

    # Stage 5: Post-process with Kinocut
    print("\n[5/5] Post-processing with Kinocut...")

    # Example: add a watermark and export
    watermarked = client.watermark(
        video=render_path,
        image="logo.png",  # Replace with your logo path
        position="bottom-right",
        opacity=0.7,
        output=os.path.join(OUTPUT_DIR, "05_watermarked.mp4"),
    )
    print(f"   -> Watermarked: {watermarked.output_path}")

    final = client.convert(
        watermarked.output_path,
        format="mp4",
        quality="high",
        output=os.path.join(OUTPUT_DIR, "final_video.mp4"),
    )
    print(f"   -> Final: {final.output_path}")

    print("\n" + "=" * 60)
    print("Workflow complete! Review output/final_video.mp4")
    print("=" * 60)


if __name__ == "__main__":
    main()
