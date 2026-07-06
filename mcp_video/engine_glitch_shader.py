"""CRUSH GPU shader effects engine — headless WebGL pipeline.

Four GPU-native CRUSH effects that can't be expressed as FFmpeg filter chains:
- Digital Feedback (effect id 10): iterative frame feedback with scale/rotation
- Slit-Scan (effect id 7): temporal displacement across multiple past frames
- Depth Splatting (effect id 11): compute-dispatched point splat from depth map
- Point Cloud (effect id 14): fragment-shader point cloud rendering

Each effect extracts frames with FFmpeg, renders via a headless Node.js/CRUSH.js
subprocess, then reassembles with FFmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import MCPVideoError, ProcessingError
from .ffmpeg_helpers import (
    _run_command,
    _validate_input_path,
    _validate_output_path,
)
from .limits import FFPROBE_TIMEOUT

# Path to the CRUSH.js module bundled with mcp-video
_CRUSH_JS_DIR = Path(__file__).resolve().parent / "_crush_shader"

# Headless render script (render_frames.mjs)
_RENDER_SCRIPT = _CRUSH_JS_DIR / "render_frames.mjs"


def _resolve_crush_path() -> str:
    """Resolve CRUSH.js source directory with multiple fallback strategies.

    Resolution order:
    1. MCP_VIDEO_CRUSH_PATH environment variable
    2. ~/.mcp-video/crush-js/src
    3. Bundled relative path (../../../../CRUSH_SHADERS/crush-js/src from render script)
    """
    env_path = os.environ.get("MCP_VIDEO_CRUSH_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.is_dir():
            return str(p)

    home_path = Path.home() / ".mcp-video" / "crush-js" / "src"
    if home_path.is_dir():
        return str(home_path)

    # Fallback: the render script itself resolves relative to its own location
    return str(_CRUSH_JS_DIR)


def _crush_sources_available() -> bool:
    """True when the CRUSH GLSL sources (not shipped with the package) are resolvable."""
    return (Path(_resolve_crush_path()) / "common.glsl").is_file()


def _crush_canvas_available() -> bool:
    """True when the `canvas` npm package resolves next to the render script.

    The wheel ships only render_frames.mjs; canvas is a native npm dependency
    users install once via ``npm install`` in the script directory.
    """
    node = shutil.which("node")
    if not node:
        return False
    probe = subprocess.run(  # noqa: S603
        [node, "-e", "require.resolve('canvas')"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_CRUSH_JS_DIR),
    )
    return probe.returncode == 0


_VIDEO_ENCODE_FLAGS = [
    "-c:a",
    "copy",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-crf",
    "23",
]


def _check_node() -> str:
    """Verify Node.js is available and return its path."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js is required for GPU shader effects. Install from https://nodejs.org or run `brew install node`."
        )
    return node


def _extract_frames(input_path: str, frames_dir: str) -> dict[str, Any]:
    """Extract video frames as PNG into frames_dir. Returns frame count."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        os.path.join(frames_dir, "frame_%06d.png"),
    ]
    _run_command(cmd)
    frames = sorted(Path(frames_dir).glob("frame_*.png"))
    return {"frame_count": len(frames)}


def _assemble_video(
    frames_dir: str,
    audio_path: str | None,
    output: str,
    fps: str | None = None,
) -> dict[str, Any]:
    """Assemble rendered frames back into video, muxing audio if available."""
    input_frame = os.path.join(frames_dir, "frame_%06d.png")
    cmd: list[str] = ["ffmpeg", "-y"]

    # Frame input
    if fps:
        cmd += ["-framerate", fps]
    cmd += ["-i", input_frame]

    # Audio from original if available
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path, "-map", "0:v", "-map", "1:a"]

    cmd += [*_VIDEO_ENCODE_FLAGS, output]
    _run_command(cmd)
    return {"output": output}


def _extract_audio(input_path: str, audio_path: str) -> bool:
    """Extract audio track from input. Returns True if audio exists."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "copy",
        audio_path,
    ]
    try:
        _run_command(cmd)
        return os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
    except Exception:
        return False


def _get_fps(input_path: str) -> str:
    """Get input video framerate."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "json",
        input_path,
    ]
    result = _run_command(cmd, timeout=FFPROBE_TIMEOUT)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProcessingError(" ".join(cmd), 0, f"Invalid JSON from ffprobe: {exc}") from None
    streams = data.get("streams", [])
    if streams:
        return streams[0].get("r_frame_rate", "30/1")
    return "30/1"


def _run_shader_effect(
    effect_name: str,
    input_path: str,
    output: str,
    params: dict[str, float],
) -> dict[str, Any]:
    """Run a CRUSH shader effect via headless Node.js subprocess.

    Steps:
    1. Extract frames from input video
    2. Run Node.js render script (loads CRUSH.js, processes each frame)
    3. Reassemble output video with audio
    """
    input_path = _validate_input_path(input_path)
    output = _validate_output_path(output)

    node = _check_node()

    if not _RENDER_SCRIPT.exists():
        raise FileNotFoundError(
            f"CRUSH shader render script not found at {_RENDER_SCRIPT}. "
            "Run the CRUSH.js setup to install GPU shader support."
        )

    with tempfile.TemporaryDirectory(prefix="crush_shader_") as tmp:
        frames_dir = os.path.join(tmp, "frames")
        rendered_dir = os.path.join(tmp, "rendered")
        audio_path = os.path.join(tmp, "audio.aac")
        os.makedirs(frames_dir)
        os.makedirs(rendered_dir)

        # Get FPS before extraction
        fps = _get_fps(input_path)

        # Extract audio (best-effort)
        has_audio = _extract_audio(input_path, audio_path)

        # Extract frames
        info = _extract_frames(input_path, frames_dir)
        frame_count = info["frame_count"]

        if frame_count == 0:
            raise RuntimeError(f"No frames extracted from {input_path}")

        max_frames = 7200
        if frame_count > max_frames:
            raise RuntimeError(
                f"Video has {frame_count} frames; GPU shader pipeline maximum is {max_frames}. "
                "Trim the video first or use the FFmpeg-based glitch effects instead."
            )

        # Build params JSON for the render script
        render_params = {
            "effect": effect_name,
            "inputDir": frames_dir,
            "outputDir": rendered_dir,
            "frameCount": frame_count,
            "params": params,
            "crushPath": _resolve_crush_path(),
        }

        # Run Node.js render
        if not _crush_sources_available():
            raise MCPVideoError(
                "CRUSH shader sources not found (common.glsl). Shader effects need the "
                "crush-js sources: set MCP_VIDEO_CRUSH_PATH to your crush-js/src directory "
                "or install them under ~/.mcp-video/crush-js/src. "
                "The FFmpeg-based glitch_* tools work without them.",
                error_type="dependency_error",
                code="missing_crush_shaders",
            )
        if not _crush_canvas_available():
            raise MCPVideoError(
                "The `canvas` npm package needed for GPU shader rendering is not installed. "
                f"Run: npm install (in {_CRUSH_JS_DIR}). "
                "The FFmpeg-based glitch_* tools work without it.",
                error_type="dependency_error",
                code="missing_canvas",
            )
        env = os.environ.copy()
        env["MCP_VIDEO_CRUSH_PATH"] = _resolve_crush_path()
        render_cmd = [node, str(_RENDER_SCRIPT), json.dumps(render_params)]
        render_result = subprocess.run(  # noqa: S603
            render_cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute max
            env=env,
        )

        if render_result.returncode != 0:
            raise RuntimeError(
                f"CRUSH shader render failed (exit {render_result.returncode}): {render_result.stderr[:500]}"
            )

        # Check rendered frames
        rendered = sorted(Path(rendered_dir).glob("frame_*.png"))
        if not rendered:
            raise RuntimeError("Shader render produced no output frames")

        # Assemble video
        _assemble_video(rendered_dir, audio_path if has_audio else None, output, fps)

    return {"output": output, "effect": effect_name, "frames_processed": frame_count}


# ---------------------------------------------------------------------------
# Effect 10: Digital Feedback
# ---------------------------------------------------------------------------


def glitch_digital_feedback(
    input_path: str,
    output: str,
    feedback_mix: float = 0.5,
    scale: float = 1.0,
    rotation: float = 0.0,
    decay: float = 0.9,
) -> dict[str, Any]:
    """Apply iterative digital feedback with scale/rotation transform.

    Each frame blends with a scaled+rotated version of the previous output,
    creating ghostly trails and recursive patterns.

    Args:
        input_path: Path to input video.
        output: Path for output video.
        feedback_mix: Blend between current and feedback (0-1). Default 0.5.
        scale: UV scale for previous frame. Default 1.0.
        rotation: Rotation in degrees. Default 0.0.
        decay: Ghost trail opacity (0-1). Default 0.9.

    Returns:
        Dict with output path and metadata.
    """
    return _run_shader_effect(
        "digital_feedback",
        input_path,
        output,
        {
            "u_feedback_mix": feedback_mix,
            "u_scale": scale,
            "u_rotation": rotation,
            "u_decay": decay,
        },
    )


# ---------------------------------------------------------------------------
# Effect 7: Slit-Scan
# ---------------------------------------------------------------------------


def glitch_slit_scan(
    input_path: str,
    output: str,
    depth: int = 30,
    direction: int = 0,
) -> dict[str, Any]:
    """Apply temporal slit-scan displacement.

    Each row/column of the output is sampled from a different past frame,
    creating a time-smeared effect reminiscent of slit-scan photography.

    Args:
        input_path: Path to input video.
        output: Path for output video.
        depth: Number of past frames to use (1-120). Default 30.
        direction: 0=top-bottom, 1=bottom-top, 2=left-right, 3=right-left. Default 0.

    Returns:
        Dict with output path and metadata.
    """
    return _run_shader_effect(
        "slit_scan",
        input_path,
        output,
        {
            "u_depth": float(depth),
            "u_direction": float(direction),
        },
    )


# ---------------------------------------------------------------------------
# Effect 11: Depth Splatting
# ---------------------------------------------------------------------------


def glitch_depth_splatting(
    input_path: str,
    output: str,
    depth_scale: float = 1.0,
    spread: float = 10.0,
    point_size: float = 3.0,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Apply depth-based point splatting effect.

    Extracts pseudo-depth from luminance and renders the image as scattered
    points, creating a 3D particle-like appearance.

    Args:
        input_path: Path to input video.
        output: Path for output video.
        depth_scale: Depth extraction intensity. Default 1.0.
        spread: Point spread distance in pixels. Default 10.0.
        point_size: Size of each splatted point. Default 3.0.
        threshold: Depth cutoff threshold (0-1). Default 0.5.

    Returns:
        Dict with output path and metadata.
    """
    return _run_shader_effect(
        "depth_splatting",
        input_path,
        output,
        {
            "u_depth_scale": depth_scale,
            "u_spread": spread,
            "u_point_size": point_size,
            "u_threshold": threshold,
        },
    )


# ---------------------------------------------------------------------------
# Effect 14: Point Cloud
# ---------------------------------------------------------------------------


def glitch_point_cloud(
    input_path: str,
    output: str,
    density: float = 0.5,
    point_size: float = 2.0,
    rotation: float = 0.0,
    depth: float = 1.0,
) -> dict[str, Any]:
    """Apply point cloud rendering effect.

    Samples the image as scattered points arranged in a 3D-rotated grid,
    with depth-based displacement creating a volumetric look.

    Args:
        input_path: Path to input video.
        output: Path for output video.
        density: Point sampling density (0-1). Default 0.5.
        point_size: Size of each point. Default 2.0.
        rotation: 3D rotation angle in degrees. Default 0.0.
        depth: Depth displacement intensity. Default 1.0.

    Returns:
        Dict with output path and metadata.
    """
    return _run_shader_effect(
        "point_cloud",
        input_path,
        output,
        {
            "u_density": density,
            "u_point_size": point_size,
            "u_rotation": rotation,
            "u_depth": depth,
        },
    )
