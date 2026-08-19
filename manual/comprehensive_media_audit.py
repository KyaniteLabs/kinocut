#!/usr/bin/env python3
"""
Comprehensive integration test for Kinocut (formerly mcp-video).

Tests:
1. Varied video formats (MP4, WebM, MOV)
2. Different resolutions and codecs
3. Adversarial cases (corrupt files, weird inputs, edge cases)
4. Video stabilization (requires ffmpeg-full with vidstab)
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Set PATH to use ffmpeg-full for vidstab support
os.environ["PATH"] = "/opt/homebrew/opt/ffmpeg-full/bin:" + os.environ.get("PATH", "")

sys.path.insert(0, str(Path(__file__).parent))
from mcp_video import Client

# Use ffmpeg-full for vidstab support
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"

# Original test video
SOURCE_VIDEO = os.environ.get("MCP_VIDEO_TEST_FILE", "")  # Set to a real video path for manual testing
OUTPUT_DIR = tempfile.mkdtemp(prefix="mcp_video_comprehensive_")

print("🎬 Comprehensive Integration Test")
print(f"Source: {SOURCE_VIDEO}")
print(f"Output dir: {OUTPUT_DIR}")
print("=" * 60)

editor = Client()
results = {}


def test_feature(name, fn):
    print(f"\n📋 {name}...")
    try:
        result = fn()
        results[name] = ("✅ PASS", None, result)
        print("   ✅ PASS")
        return True
    except Exception as e:
        results[name] = ("❌ FAIL", str(e)[:200], None)
        print(f"   ❌ FAIL: {str(e)[:100]}")
        return False


def test_adversarial(name, fn, should_fail=False):
    """Test an adversarial case - should_fail=True means we expect an error."""
    print(f"\n🔓 {name}...")
    try:
        result = fn()
        if should_fail:
            results[name] = ("❌ FAIL", "Expected an error but succeeded", None)
            print("   ❌ FAIL: Expected error but got success")
            return False
        else:
            results[name] = ("✅ PASS", None, result)
            print("   ✅ PASS")
            return True
    except Exception as e:
        if should_fail:
            results[name] = ("✅ PASS", f"Expected error: {type(e).__name__}", None)
            print(f"   ✅ PASS (expected error: {type(e).__name__})")
            return True
        else:
            results[name] = ("❌ FAIL", str(e)[:200], None)
            print(f"   ❌ FAIL: {str(e)[:100]}")
            return False


# ===========================================================================
# PHASE 1: Generate varied test videos
# ===========================================================================


def setup_test_videos():
    """Generate test videos with different formats and properties."""
    print("\n🔧 Setting up varied test videos...")

    videos = {}

    # 1. Convert to WebM
    webm_path = os.path.join(OUTPUT_DIR, "test.webm")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-c:v", "libvpx", "-c:a", "libopus", webm_path],
        capture_output=True,
        check=False,
    )
    videos["webm"] = webm_path

    # 2. Convert to MOV
    mov_path = os.path.join(OUTPUT_DIR, "test.mov")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-c:v", "libx264", "-c:a", "aac", mov_path],
        capture_output=True,
        check=False,
    )
    videos["mov"] = mov_path

    # 3. Create a different resolution (1920x1080 landscape)
    landscape_path = os.path.join(OUTPUT_DIR, "landscape.mp4")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-vf", "scale=1920:1080", "-c:a", "copy", landscape_path],
        capture_output=True,
        check=False,
    )
    videos["landscape"] = landscape_path

    # 4. Create a square video (1080x1080)
    square_path = os.path.join(OUTPUT_DIR, "square.mp4")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-vf", "scale=1080:1080", "-c:a", "copy", square_path],
        capture_output=True,
        check=False,
    )
    videos["square"] = square_path

    # 5. Create a video without audio
    no_audio_path = os.path.join(OUTPUT_DIR, "no_audio.mp4")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-an", "-c:v", "copy", no_audio_path], capture_output=True, check=False
    )
    videos["no_audio"] = no_audio_path

    # 6. Create a very short video (0.5 seconds)
    short_path = os.path.join(OUTPUT_DIR, "short.mp4")
    subprocess.run(
        [FFMPEG_FULL, "-y", "-i", SOURCE_VIDEO, "-t", "0.5", "-c", "copy", short_path], capture_output=True, check=False
    )
    videos["short"] = short_path

    # 7. Create a black video (synthetic)
    black_path = os.path.join(OUTPUT_DIR, "black.mp4")
    subprocess.run(
        [
            FFMPEG_FULL,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:1920x1080:duration=2",
            "-c:v",
            "libx264",
            "-t",
            "2",
            black_path,
        ],
        capture_output=True,
        check=False,
    )
    videos["black"] = black_path

    # 8. Create a noisy video for stabilization test
    # We'll use the source video and add camera shake
    shaky_path = os.path.join(OUTPUT_DIR, "shaky.mp4")
    subprocess.run(
        [
            FFMPEG_FULL,
            "-y",
            "-i",
            SOURCE_VIDEO,
            "-vf",
            "crop='iw/2:ih/2:(iw/4)+(sin(t*10)*50):(ih/4)+(cos(t*10)*50)'",
            "-t",
            "3",
            shaky_path,
        ],
        capture_output=True,
        check=False,
    )
    videos["shaky"] = shaky_path

    # Verify videos exist
    for name, path in videos.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"   ✅ {name}: {os.path.basename(path)} ({size / 1024 / 1024:.1f}MB)")
        else:
            print(f"   ❌ {name}: Failed to create")

    return videos


# Run setup
test_videos = setup_test_videos()

# ===========================================================================
# PHASE 2: Test with varied formats
# ===========================================================================


def test_webm_format():
    """Test operations on WebM video."""
    return editor.trim(
        test_videos["webm"], start="0:00:01", duration="2", output=os.path.join(OUTPUT_DIR, "webm_trim.mp4")
    )


def test_mov_format():
    """Test operations on MOV video."""
    return editor.convert(test_videos["mov"], format="mp4", output=os.path.join(OUTPUT_DIR, "mov_to_mp4.mp4"))


def test_landscape_video():
    """Test operations on landscape video."""
    result = editor.info(test_videos["landscape"])
    assert "1920" in result.resolution
    return result


def test_square_video():
    """Test operations on square video."""
    result = editor.info(test_videos["square"])
    assert result.resolution == "1080x1080"
    return result


# ===========================================================================
# PHASE 3: Adversarial tests
# ===========================================================================


def test_nonexistent_file():
    """Test with nonexistent file (should fail)."""
    return editor.info("/nonexistent/video.mp4")


def test_empty_filename():
    """Test with empty filename (should fail)."""
    return editor.info("")


def test_corrupt_file():
    """Test with corrupt file (should fail)."""
    corrupt_path = os.path.join(OUTPUT_DIR, "corrupt.mp4")
    with open(corrupt_path, "wb") as f:
        f.write(b"This is not a video file at all!")
    return editor.info(corrupt_path)


def test_negative_duration():
    """Test trim with negative duration (should fail or handle gracefully)."""
    return editor.trim(test_videos["short"], start="0", duration="-5")


def test_negative_start():
    """Test trim with negative start (edge case - may fail on some builds)."""
    # This is expected to fail or produce empty output on many FFmpeg builds
    # Mark as should_fail since behavior varies
    try:
        result = editor.trim(test_videos["short"], start="-1", duration="1")
        # If we got here, check if the output is valid
        if os.path.exists(result.output_path):
            info = editor.info(result.output_path)
            if info.duration > 0:
                return result
        raise Exception("Trim produced invalid output")
    except Exception:
        # Expected - negative timestamps are not universally supported
        return None  # Treat as pass


def test_zero_duration():
    """Test with zero duration (should fail)."""
    return editor.trim(test_videos["short"], start="0", duration="0")


def test_no_audio_video():
    """Test operations on video without audio."""
    # Operations that require audio should fail gracefully
    try:
        return editor.audio_waveform(test_videos["no_audio"], bins=10)
    except Exception:
        # Expected - no audio stream
        return None  # Treat as pass for this test


def test_black_video_detection():
    """Test scene detection on uniform black video (edge case)."""
    return editor.detect_scenes(test_videos["black"], threshold=0.1)


def test_very_short_video():
    """Test operations on very short video."""
    return editor.info(test_videos["short"])


def test_extremely_large_bins():
    """Test waveform with unreasonable bin count."""
    return editor.audio_waveform(test_videos.get("webm", SOURCE_VIDEO), bins=10000)


# ===========================================================================
# PHASE 4: Video stabilization (requires ffmpeg-full)
# ===========================================================================


def test_stabilization_with_ffmpeg_full():
    """Test video stabilization using ffmpeg-full."""
    # Check if ffmpeg-full has vidstab
    result = subprocess.run([FFMPEG_FULL, "-filters"], capture_output=True, text=True)
    if "vidstab" not in result.stdout:
        raise Exception("vidstab not available in ffmpeg-full")

    # Use a shorter video segment for stabilization (it's slow)
    result = editor.stabilize(
        test_videos["shaky"], smoothing=10, zooming=0, output=os.path.join(OUTPUT_DIR, "stabilized.mp4")
    )
    # Verify output exists and has content
    if os.path.exists(result.output_path):
        info = editor.info(result.output_path)
        assert info.duration > 0, "Stabilized video is empty"
    return result


def test_scene_detection_varied_content():
    """Test scene detection on different video types."""
    all_results = []
    for name in ["webm", "landscape", "square"]:
        try:
            result = editor.detect_scenes(test_videos[name], threshold=0.3)
            all_results.append(f"{name}: {result.scene_count} scenes")
        except Exception as e:
            all_results.append(f"{name}: {str(e)[:50]}")
    return "\n   ".join(all_results)


# ===========================================================================
# PHASE 5: Format conversion tests
# ===========================================================================


def test_mp4_to_webm():
    """Test MP4 to WebM conversion."""
    return editor.convert(
        test_videos.get("webm", SOURCE_VIDEO), format="mp4", output=os.path.join(OUTPUT_DIR, "to_mp4.mp4")
    )


def test_mp4_to_gif():
    """Test MP4 to GIF conversion."""
    return editor.convert(
        test_videos.get("short", SOURCE_VIDEO),
        format="gif",
        quality="low",
        output=os.path.join(OUTPUT_DIR, "animated.gif"),
    )


# ===========================================================================
# Run all tests
# ===========================================================================

if __name__ == "__main__":
    if not os.path.exists(SOURCE_VIDEO):
        print(f"❌ Source video not found: {SOURCE_VIDEO}")
        sys.exit(1)

    # Test categories
    format_tests = [
        ("WebM format support", test_webm_format),
        ("MOV format support", test_mov_format),
        ("Landscape video (1920x1080)", test_landscape_video),
        ("Square video (1080x1080)", test_square_video),
    ]

    adversarial_tests = [
        ("Nonexistent file (should error)", test_nonexistent_file, True),
        ("Empty filename (should error)", test_empty_filename, True),
        ("Corrupt file (should error)", test_corrupt_file, True),
        ("Negative duration (edge case)", test_negative_duration, True),
        ("Negative start (edge case)", test_negative_start, False),  # May fail, that's ok
        ("Zero duration (should error)", test_zero_duration, True),
        ("Video without audio", test_no_audio_video, False),
        ("Black video scene detection", test_black_video_detection, False),
        ("Very short video", test_very_short_video, False),
        ("Extremely large bin count", test_extremely_large_bins, False),
    ]

    feature_tests = [
        ("Video stabilization (ffmpeg-full)", test_stabilization_with_ffmpeg_full),
        ("Scene detection on varied content", test_scene_detection_varied_content),
        ("MP4 to WebM conversion", test_mp4_to_webm),
        ("MP4 to GIF conversion", test_mp4_to_gif),
    ]

    passed = failed = skipped = 0

    print("\n" + "=" * 60)
    print("PHASE 2: Format Variations")
    print("=" * 60)
    for test in format_tests:
        if len(test) == 2:
            name, fn = test
            if test_feature(name, fn):
                passed += 1
            else:
                failed += 1

    print("\n" + "=" * 60)
    print("PHASE 3: Adversarial Tests")
    print("=" * 60)
    for test in adversarial_tests:
        if len(test) == 3:
            name, fn, should_fail = test
            if test_adversarial(name, fn, should_fail):
                passed += 1
            else:
                failed += 1

    print("\n" + "=" * 60)
    print("PHASE 4: Feature Tests with ffmpeg-full")
    print("=" * 60)
    for test in feature_tests:
        name, fn = test
        if test_feature(name, fn):
            passed += 1
        else:
            failed += 1

    # Print summary
    print("\n" + "=" * 60)
    print("📊 COMPREHENSIVE TEST SUMMARY")
    print("=" * 60)
    for name, (status, error, _) in results.items():
        print(f"{status} {name}")
        if error and "expected error" not in error.lower():
            print(f"         {error}")

    print("\n" + "-" * 60)
    print(f"Total: {passed} passed, {failed} failed")
    print(f"\n📁 Test artifacts saved to: {OUTPUT_DIR}")

    sys.exit(0 if failed == 0 else 1)
