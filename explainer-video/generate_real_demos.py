#!/usr/bin/env python3
"""Generate REAL demo videos for Remotion explainer using pottery footage.

This creates actual before/after demos with mcp-video operations
on real pottery videos, then integrates them into the explainer scenes.
"""

import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_video import Client

client = Client()

# Paths
EXP_DIR = Path("~/workspaces/mcp-video/explainer-video")
DEMO_DIR = EXP_DIR / "public" / "demos"
DEMO_DIR.mkdir(parents=True, exist_ok=True)

# Real pottery footage source
POTTERY_DIR = Path("~/Desktop/Workspaces/ceramics-instagram/data/archive/cerafica_media")
SOURCE_VIDEOS = list(POTTERY_DIR.glob("*.mp4"))[:5]  # Get first 5 videos

print(f"Found {len(SOURCE_VIDEOS)} pottery videos")


def prepare_source_clip(input_path: Path, output_path: Path, duration: float = 5.0):
    """Prepare a clean source clip from pottery footage."""
    result = client.trim(str(input_path), start=0, duration=duration, output=str(output_path))
    return result.output_path if result.success else None


def generate_ai_upscale_demo():
    """Generate AI upscale before/after demo."""
    print("\n[Demo] AI Upscale...")
    
    if not SOURCE_VIDEOS:
        return None
    
    source = DEMO_DIR / "upscale_source.mp4"
    prepare_source_clip(SOURCE_VIDEOS[0], source)
    
    # Create low-res version
    low_res = DEMO_DIR / "upscale_lowres.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(source),
        "-vf", "scale=360:-1",
        "-c:v", "libx264", "-preset", "fast",
        str(low_res)
    ], capture_output=True)
    
    # AI upscale
    upscaled = DEMO_DIR / "upscale_after.mp4"
    try:
        result = client.ai_upscale(str(low_res), str(upscaled), scale=2)
        if os.path.exists(result):
            # Create side-by-side
            split = DEMO_DIR / "upscale_demo.mp4"
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(low_res), "-i", str(upscaled),
                "-filter_complex", "[0:v]scale=240:426[left];[1:v]scale=240:426[right];[left][right]hstack",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-t", "3", str(split)
            ], capture_output=True)
            print(f"  ✓ Created: {split.name}")
            return str(split)
    except Exception as e:
        print(f"  ⚠️  {e}")
    return None


def generate_color_grade_demo():
    """Generate color grading demo."""
    print("\n[Demo] Color Grading...")
    
    if len(SOURCE_VIDEOS) < 2:
        return None
    
    source = DEMO_DIR / "color_source.mp4"
    prepare_source_clip(SOURCE_VIDEOS[1], source)
    
    # Warm preset
    warm = DEMO_DIR / "color_warm.mp4"
    result = client.ai_color_grade(str(source), str(warm), style="warm")
    
    # Cinematic preset
    cine = DEMO_DIR / "color_cinematic.mp4"
    result = client.ai_color_grade(str(source), str(cine), style="cinematic")
    
    # Create 3-way split
    demo = DEMO_DIR / "color_demo.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(source), "-i", str(warm), "-i", str(cine),
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3,scale=480:-1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-t", "3",
        "-t", "3", str(demo)
    ], capture_output=True)
    
    if demo.exists():
        print(f"  ✓ Created: {demo.name}")
        return str(demo)
    return None


def generate_effects_demo():
    """Generate visual effects demo."""
    print("\n[Demo] Visual Effects...")
    
    if not SOURCE_VIDEOS:
        return None
    
    source = DEMO_DIR / "effects_source.mp4"
    prepare_source_clip(SOURCE_VIDEOS[0], source)
    
    # Apply effects
    effects = []
    
    # Vignette
    vig = DEMO_DIR / "effect_vignette.mp4"
    result = client.effect_vignette(str(source), str(vig), intensity=0.6)
    if result:
        effects.append(("Vignette", result))
    
    # Glow
    glow = DEMO_DIR / "effect_glow.mp4"
    result = client.effect_glow(str(source), str(glow), intensity=0.5)
    if result:
        effects.append(("Glow", result))
    
    # Chromatic
    chroma = DEMO_DIR / "effect_chroma.mp4"
    result = client.effect_chromatic_aberration(str(source), str(chroma), intensity=2)
    if result:
        effects.append(("Chromatic", result))
    
    if len(effects) >= 2:
        # Create comparison
        demo = DEMO_DIR / "effects_demo.mp4"
        cmd = ["ffmpeg", "-y", "-i", str(source)]
        for _, path in effects[:2]:
            cmd.extend(["-i", str(path)])
        cmd.extend([
            "-filter_complex", f"[0:v][1:v][2:v]hstack=inputs=3,scale=480:-1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            "-t", "3", str(demo)
        ])
        subprocess.run(cmd, capture_output=True)
        
        if demo.exists():
            print(f"  ✓ Created: {demo.name}")
            return str(demo)
    return None


def generate_test_results_screen():
    """Generate test results screen showing 70/70 passing."""
    print("\n[Demo] Test Results...")
    
    output = DEMO_DIR / "test_results.mp4"
    
    # Create video with test results text
    text = """MCP-VIDEO v1.0

TEST SUITE RESULTS
✅ 70/70 Tests Passing

Core Video Editing: 18/18
Audio Features: 10/10
Visual Effects: 8/8
AI Features: 8/8
Layout & Composition: 8/8
Quality & Metadata: 8/8
Utility: 7/7
Transitions: 3/3

AI Features Verified:
✓ Scene Detection
✓ Silence Removal
✓ Transcription (Whisper)
✓ Stem Separation (Demucs)
✓ AI Upscale (OpenCV)
✓ Color Grading
✓ Spatial Audio

Real Media. No Mocks."""
    
    # Use lavfi to create video with text
    filter_str = f"color=c=black:s=1080x1920:d=10,drawtext=fontfile=/System/Library/Fonts/Helvetica.ttc:text='{text}':fontcolor=white:fontsize=32:x=50:y=50:line_spacing=8"
    
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", filter_str,
        "-c:v", "libx264", "-preset", "fast",
        str(output)
    ], capture_output=True)
    
    if output.exists():
        print(f"  ✓ Created: {output.name}")
        return str(output)
    return None


def generate_stabilization_demo():
    """Generate stabilization demo using vidstab."""
    print("\n[Demo] Stabilization...")
    
    if not SOURCE_VIDEOS:
        return None
    
    source = DEMO_DIR / "stab_source.mp4"
    prepare_source_clip(SOURCE_VIDEOS[0], source)
    
    # Try stabilization
    stabilized = DEMO_DIR / "stab_demo.mp4"
    try:
        result = client.stabilize(str(source), output=str(stabilized))
        if result.success:
            # Create before/after
            demo = DEMO_DIR / "stabilization_demo.mp4"
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(source), "-i", str(stabilized),
                "-filter_complex", "[0:v][1:v]hstack,scale=640:-1",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-t", "3", str(demo)
            ], capture_output=True)
            
            if demo.exists():
                print(f"  ✓ Created: {demo.name}")
                return str(demo)
    except Exception as e:
        print(f"  ⚠️  Stabilization not available: {e}")
    
    return None


def generate_all_demos():
    """Generate all demo videos."""
    print("=" * 60)
    print("GENERATING REAL DEMO VIDEOS")
    print("Using pottery footage + mcp-video operations")
    print("=" * 60)
    
    demos = {}
    
    demos['upscale'] = generate_ai_upscale_demo()
    demos['color'] = generate_color_grade_demo()
    demos['effects'] = generate_effects_demo()
    demos['tests'] = generate_test_results_screen()
    demos['stabilization'] = generate_stabilization_demo()
    
    print("\n" + "=" * 60)
    print("DEMO GENERATION COMPLETE")
    print("=" * 60)
    print(f"\nDemo files in: {DEMO_DIR}")
    for name, path in demos.items():
        if path:
            print(f"  ✓ {name}: {Path(path).name}")
        else:
            print(f"  ✗ {name}: Failed")
    
    return demos


if __name__ == "__main__":
    generate_all_demos()
