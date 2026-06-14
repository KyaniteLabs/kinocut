"""Tests for video transitions."""

import tempfile
import os
import subprocess

import pytest


def create_test_video(output_path, duration=2, color="red"):
    """Helper to create test video using FFmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x240:d={duration}",
        "-pix_fmt",
        "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


def test_glitch_transition():
    """Test glitch transition creates output file."""
    from mcp_video.transitions_engine import transition_glitch

    with tempfile.TemporaryDirectory() as tmpdir:
        clip1 = os.path.join(tmpdir, "clip1.mp4")
        clip2 = os.path.join(tmpdir, "clip2.mp4")
        output = os.path.join(tmpdir, "output.mp4")

        create_test_video(clip1, duration=2, color="red")
        create_test_video(clip2, duration=2, color="blue")

        result = transition_glitch(clip1, clip2, output, duration=0.5)

        assert os.path.exists(result), "Output file not created"
        assert os.path.getsize(result) > 0, "Output file is empty"
        print(f"✓ Glitch transition created: {os.path.getsize(result)} bytes")


def test_morph_transition():
    """Test morph transition creates output file."""
    from mcp_video.transitions_engine import transition_morph

    with tempfile.TemporaryDirectory() as tmpdir:
        clip1 = os.path.join(tmpdir, "clip1.mp4")
        clip2 = os.path.join(tmpdir, "clip2.mp4")
        output = os.path.join(tmpdir, "output.mp4")

        create_test_video(clip1, duration=2, color="purple")
        create_test_video(clip2, duration=2, color="orange")

        result = transition_morph(clip1, clip2, output, duration=0.6, mesh_size=10)

        assert os.path.exists(result), "Output file not created"
        assert os.path.getsize(result) > 0, "Output file is empty"
        print(f"✓ Morph transition created: {os.path.getsize(result)} bytes")


@pytest.mark.slow
def test_pixelate_transition():
    """Test pixelate transition creates output file."""
    from mcp_video.transitions_engine import transition_pixelate

    with tempfile.TemporaryDirectory() as tmpdir:
        clip1 = os.path.join(tmpdir, "clip1.mp4")
        clip2 = os.path.join(tmpdir, "clip2.mp4")
        output = os.path.join(tmpdir, "output.mp4")

        create_test_video(clip1, duration=2, color="green")
        create_test_video(clip2, duration=2, color="yellow")

        result = transition_pixelate(clip1, clip2, output, duration=0.4, pixel_size=50)

        assert os.path.exists(result), "Output file not created"
        assert os.path.getsize(result) > 0, "Output file is empty"
        print(f"✓ Pixelate transition created: {os.path.getsize(result)} bytes")


if __name__ == "__main__":
    test_glitch_transition()
    test_morph_transition()
    test_pixelate_transition()
