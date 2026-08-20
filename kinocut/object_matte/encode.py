"""Write object-matte RGBA stills and alpha-capable videos via FFmpeg."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..defaults import DEFAULT_OBJECT_MATTE_TIMEOUT
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_command, _validate_output_path
from ..validation import OBJECT_MATTE_ALPHA_SUFFIXES


def assert_alpha_output(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix not in OBJECT_MATTE_ALPHA_SUFFIXES:
        raise MCPVideoError(
            f"Object-matte output must be .webm (VP9+alpha), .mov (ProRes yuva), or .png, got {suffix!r}.",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url="docs/PRODUCT_MATTE.md",
        )
    return _validate_output_path(path)


def write_png(image: Image.Image, output_path: str) -> str:
    dest = assert_alpha_output(output_path)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(dest)
    return dest


def write_alpha_video(frame_dir: Path, output_path: str, fps: float, pattern: str) -> str:
    dest = assert_alpha_output(output_path)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    suffix = Path(dest).suffix.lower()
    source = str(frame_dir / pattern)
    if suffix == ".webm":
        codec = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0"]
    elif suffix == ".mov":
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
    else:
        raise MCPVideoError(
            "Video object-matte output must be .webm or .mov",
            error_type="validation_error",
            code="invalid_parameter",
        )
    rate = f"{fps:.6f}".rstrip("0").rstrip(".")
    _run_command(
        ["ffmpeg", "-y", "-framerate", rate, "-i", source, *codec, "-an", dest],
        timeout=DEFAULT_OBJECT_MATTE_TIMEOUT,
    )
    return dest
