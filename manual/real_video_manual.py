#!/usr/bin/env python3
"""Real video integration test for all 11 new FFmpeg features from Waves 1-5."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_video import Client

TEST_VIDEO = "~/Desktop/Workspaces/ceramics-instagram/data/archive/cerafica_media/2023-04-23_14-43-35_UTC.mp4"
OUTPUT_DIR = tempfile.mkdtemp(prefix="mcp_video_real_test_")

print("🎬 Real Video Integration Test")
print(f"Input: {TEST_VIDEO}")
print(f"Output dir: {OUTPUT_DIR}")
print("=" * 60)

editor = Client()
results = {}


def test_feature(name, fn):
    print(f"\n📋 Testing: {name}...")
    try:
        result = fn()
        results[name] = ("✅ PASS", None, result)
        print("   ✅ PASS")
        return True
    except Exception as e:
        results[name] = ("❌ FAIL", str(e), None)
        print(f"   ❌ FAIL: {e}")
        return False


# Wave 1: Ken Burns effect (via filter), Two-pass encoding
def test_ken_burns():
    out = os.path.join(OUTPUT_DIR, "ken_burns.mp4")
    return editor.filter(TEST_VIDEO, filter_type="ken_burns", params={"zoom_speed": 0.002, "duration": 100}, output=out)


def test_two_pass():
    out = os.path.join(OUTPUT_DIR, "two_pass.mp4")
    return editor.convert(TEST_VIDEO, quality="high", two_pass=True, target_bitrate=2000, output=out)


# Wave 2: Audio effects (via filter - use direct type)
def test_audio_reverb():
    out = os.path.join(OUTPUT_DIR, "reverb.mp4")
    return editor.filter(TEST_VIDEO, filter_type="reverb", output=out)


def test_audio_compressor():
    out = os.path.join(OUTPUT_DIR, "compressed.mp4")
    return editor.filter(TEST_VIDEO, filter_type="compressor", output=out)


def test_pitch_shift():
    out = os.path.join(OUTPUT_DIR, "pitch_shift.mp4")
    return editor.filter(TEST_VIDEO, filter_type="pitch_shift", params={"semitones": 2}, output=out)


def test_noise_reduction():
    out = os.path.join(OUTPUT_DIR, "denoised.mp4")
    return editor.filter(TEST_VIDEO, filter_type="noise_reduction", output=out)


# Wave 3: Scene detection, Image sequences, Quality metrics, Metadata
def test_detect_scenes():
    result = editor.detect_scenes(TEST_VIDEO, threshold=0.3)
    assert result.scenes is not None
    assert result.scene_count >= 0
    print(f"   Found {result.scene_count} scenes")
    return result


def test_export_frames():
    out_dir = os.path.join(OUTPUT_DIR, "frames")
    return editor.export_frames(TEST_VIDEO, output_dir=out_dir, fps=1, format="jpg")


def test_compare_quality():
    compressed = os.path.join(OUTPUT_DIR, "for_quality_test.mp4")
    editor.convert(TEST_VIDEO, quality="low", output=compressed)
    result = editor.compare_quality(TEST_VIDEO, compressed, metrics=["psnr", "ssim"])
    assert "psnr" in result.metrics or "ssim" in result.metrics
    print(f"   Quality: {result.overall_quality}")
    return result


def test_read_metadata():
    result = editor.read_metadata(TEST_VIDEO)
    print(f"   Title: {result.title}")
    return result


def test_write_metadata():
    out = os.path.join(OUTPUT_DIR, "tagged.mp4")
    return editor.write_metadata(TEST_VIDEO, metadata={"title": "Test Video", "comment": "Real video test"}, output=out)


# Wave 4: Video stabilization, Advanced masking
def test_stabilize():
    out = os.path.join(OUTPUT_DIR, "stabilized.mp4")
    try:
        return editor.stabilize(TEST_VIDEO, smoothing=15, zooming=0, output=out)
    except Exception as e:
        if "vidstab" in str(e).lower():
            print("   ⚠️  SKIPPED: vidstab not available")
            results["stabilize"] = ("⚠️  SKIP", "vidstab not available", None)
            return None
        raise


def test_apply_mask():
    mask_path = os.path.join(OUTPUT_DIR, "mask.png")
    # Create a simple gradient mask using Python PIL
    from PIL import Image

    img = Image.new("RGB", (720, 1280), color="black")
    pixels = img.load()
    for y in range(1280):
        for x in range(720):
            # Create a radial gradient
            cx, cy = 360, 640
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            max_dist = (360**2 + 640**2) ** 0.5
            brightness = int(255 * (1 - dist / max_dist))
            pixels[x, y] = (brightness, brightness, brightness)
    img.save(mask_path)
    out = os.path.join(OUTPUT_DIR, "masked.mp4")
    return editor.apply_mask(TEST_VIDEO, mask=mask_path, feather=5, output=out)


# Wave 5: Subtitle generation, Audio waveform
def test_generate_subtitles():
    entries = [
        {"start": 0.0, "end": 2.0, "text": "First subtitle"},
        {"start": 2.0, "end": 4.0, "text": "Second subtitle"},
        {"start": 4.0, "end": 6.0, "text": "Third subtitle"},
    ]
    return editor.generate_subtitles(TEST_VIDEO, entries=entries, burn=True)


def test_audio_waveform():
    result = editor.audio_waveform(TEST_VIDEO, bins=20)
    assert result.peaks is not None
    assert len(result.peaks) > 0
    print(f"   Duration: {result.duration}s, Peaks: {len(result.peaks)}")
    return result


if __name__ == "__main__":
    if not os.path.exists(TEST_VIDEO):
        print(f"❌ Test video not found: {TEST_VIDEO}")
        sys.exit(1)

    info = editor.info(TEST_VIDEO)
    print(f"Video info: {info.resolution}, {info.duration:.1f}s, {info.codec}")

    tests = [
        ("Ken Burns effect", test_ken_burns),
        ("Two-pass encoding", test_two_pass),
        ("Audio reverb", test_audio_reverb),
        ("Audio compressor", test_audio_compressor),
        ("Pitch shift", test_pitch_shift),
        ("Noise reduction", test_noise_reduction),
        ("Scene detection", test_detect_scenes),
        ("Export frames", test_export_frames),
        ("Quality metrics (PSNR/SSIM)", test_compare_quality),
        ("Read metadata", test_read_metadata),
        ("Write metadata", test_write_metadata),
        ("Video stabilization", test_stabilize),
        ("Apply mask", test_apply_mask),
        ("Generate subtitles", test_generate_subtitles),
        ("Audio waveform", test_audio_waveform),
    ]

    passed = failed = skipped = 0
    for name, test_fn in tests:
        if test_feature(name, test_fn):
            passed += 1
        else:
            status = results[name][0]
            if "SKIP" in status:
                skipped += 1
            else:
                failed += 1

    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    for name, (status, error, _) in results.items():
        print(f"{status} {name}")
        if error and "SKIP" not in status:
            print(f"         Error: {error[:100]}")

    print("\n" + "-" * 60)
    print(f"Total: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"\n📁 Output files saved to: {OUTPUT_DIR}")

    sys.exit(0 if failed == 0 else 1)
