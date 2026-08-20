"""Load stills/video and encode alpha cutouts plus inverse-alpha plates."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from ..defaults import DEFAULT_FPS, DEFAULT_OBJECT_MATTE_TIMEOUT, OBJECT_MATTE_STILL_SUFFIXES
from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import (
    _get_video_duration,
    _run_command,
    _run_ffprobe_json,
    _validate_input_path,
    _validate_output_path,
)
from ..limits import MAX_OBJECT_MATTE_FRAMES

_DOCS = "docs/PRODUCT_MATTE.md"


def is_still(path: str) -> bool:
    return Path(path).suffix.lower() in OBJECT_MATTE_STILL_SUFFIXES


def default_output_path(input_path: str, output_path: str | None) -> str:
    if output_path:
        return _validate_output_path(output_path)
    suffix = ".png" if is_still(input_path) else ".webm"
    return _validate_output_path(str(Path(input_path).with_name(f"{Path(input_path).stem}-cutout{suffix}")))


def apply_alpha(image: Image.Image, mask: Image.Image, *, invert: bool = False) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = mask.convert("L").resize(rgba.size, Image.Resampling.NEAREST)
    if invert:
        alpha = ImageOps.invert(alpha)
    rgba.putalpha(alpha)
    return rgba


def load_still(path: str) -> Image.Image:
    return Image.open(_validate_input_path(path)).convert("RGB")


def _probe_video(path: str) -> tuple[float, float, int]:
    payload = _run_ffprobe_json(path)
    streams = [item for item in payload.get("streams", []) if item.get("codec_type") == "video"]
    if not streams:
        raise MCPVideoError(
            "Object matte needs a video stream or a still image.",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url=_DOCS,
        )
    stream = streams[0]
    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1")
    try:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den) if float(den) else DEFAULT_FPS
    except (TypeError, ValueError, ZeroDivisionError):
        fps = float(DEFAULT_FPS)
    duration = _get_video_duration(path)
    raw_frames = stream.get("nb_frames")
    try:
        count = int(raw_frames) if raw_frames not in {None, "N/A", ""} else round(duration * fps)
    except (TypeError, ValueError):
        count = round(duration * fps)
    return fps, duration, max(count, 1)


def extract_frames(path: str) -> tuple[list[Image.Image], float]:
    """Decode every frame. Caller must have already enforced the frame cap."""
    fps, _duration, count = _probe_video(path)
    if count > MAX_OBJECT_MATTE_FRAMES:
        raise MCPVideoError(
            f"Object matte refuses {count} frames (max {MAX_OBJECT_MATTE_FRAMES}). "
            "Trim the clip or raise the interval after a shorter source. "
            f"Guide: {_DOCS}.",
            error_type="validation_error",
            code="too_many_frames",
            docs_url=_DOCS,
        )
    with tempfile.TemporaryDirectory(prefix="kinocut-object-matte-") as tmp:
        pattern = os.path.join(tmp, "frame_%06d.png")
        _run_command(
            ["ffmpeg", "-y", "-i", path, "-vsync", "0", pattern],
            timeout=DEFAULT_OBJECT_MATTE_TIMEOUT,
        )
        frames = [Image.open(item).convert("RGB") for item in sorted(Path(tmp).glob("frame_*.png"))]
    if not frames:
        raise ProcessingError("ffmpeg extract frames", -1, "No frames decoded for object matte")
    return frames, fps


def encode_still(image: Image.Image, dest: str) -> str:
    path = _validate_output_path(dest)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _encode_args(dest: str) -> list[str]:
    suffix = Path(dest).suffix.lower()
    if suffix == ".webm":
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0"]
    if suffix == ".mov":
        return ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
    raise MCPVideoError(
        "Object-matte video output must be .webm (VP9+alpha) or .mov (ProRes 4444). "
        f"Got {suffix or 'no suffix'}. Guide: {_DOCS}.",
        error_type="validation_error",
        code="invalid_parameter",
        docs_url=_DOCS,
    )


def encode_video(frames: list[Image.Image], dest: str, fps: float) -> str:
    path = _validate_output_path(dest)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kinocut-object-matte-enc-") as tmp:
        for index, frame in enumerate(frames, start=1):
            frame.save(os.path.join(tmp, f"frame_{index:06d}.png"))
        pattern = os.path.join(tmp, "frame_%06d.png")
        _run_command(
            [
                "ffmpeg",
                "-y",
                "-framerate",
                str(fps or DEFAULT_FPS),
                "-i",
                pattern,
                *_encode_args(path),
                path,
            ],
            timeout=DEFAULT_OBJECT_MATTE_TIMEOUT,
        )
    return path
