"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import hashlib
import logging
import math
import ssl
import tempfile
from pathlib import Path

from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _get_video_duration, _run_command, _validate_input_path, _validate_output_path
from ..limits import DEFAULT_FFMPEG_TIMEOUT, MAX_AI_UPSCALE_FRAMES

logger = logging.getLogger(__name__)

# Expected SHA256 hashes for downloaded model files.
_MODEL_HASHES: dict[str, str] = {
    "FSRCNN_x2.pb": "366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c",
    "FSRCNN_x4.pb": "5c68d18db561aed8ead4ffedf1b897ea615baaf60ebf6c35f8e641f8fa4a21bf",
}


def _estimate_frame_count(video_path: str) -> int:
    duration = _get_video_duration(video_path)
    fps = _get_video_fps(video_path)
    if fps is None:
        raise MCPVideoError(
            "Could not determine video frame rate for AI upscaling resource check",
            error_type="validation_error",
            code="unknown_frame_rate",
        )
    return math.ceil(duration * fps)


def _validate_upscale_resource_limits(video_path: str) -> None:
    frame_count = _estimate_frame_count(video_path)
    if frame_count > MAX_AI_UPSCALE_FRAMES:
        raise MCPVideoError(
            f"Video frame count ({frame_count}) exceeds AI upscaling maximum of {MAX_AI_UPSCALE_FRAMES}",
            error_type="resource_error",
            code="frame_count_too_large",
        )


def _verify_model_hash(path: Path, expected_hash: str) -> None:
    """Verify SHA256 hash of a downloaded model file.

    Args:
        path: Path to the model file on disk.
        expected_hash: Expected lowercase hex SHA256 digest.

    Raises:
        MCPVideoError: If the computed hash does not match the expected value.
    """
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha256 != expected_hash:
        path.unlink(missing_ok=True)
        raise MCPVideoError(
            f"SHA256 integrity check failed for {path.name}: "
            f"expected {expected_hash}, got {sha256}. "
            "The downloaded file has been removed. Try again to re-download.",
            error_type="integrity_error",
            code="model_hash_mismatch",
        )


def _download_fsrcnn_model(scale: int) -> Path:
    """Download and verify FSRCNN model for OpenCV DNN Super Resolution.

    Args:
        scale: Upscaling factor (2 or 4).

    Returns:
        Path to the verified model file.
    """
    import urllib.request

    model_urls = {
        2: "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x2.pb",
        4: "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x4.pb",
    }

    if scale not in model_urls:
        raise MCPVideoError(
            f"Scale must be 2 or 4, got {scale}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    cache_dir = Path.home() / ".cache" / "mcp-video" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_path = cache_dir / f"FSRCNN_x{scale}.pb"
    model_filename = model_path.name

    if model_filename not in _MODEL_HASHES:
        raise MCPVideoError(
            f"No known hash for model {model_filename}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    expected_hash = _MODEL_HASHES[model_filename]

    if not model_path.exists():
        url = model_urls[scale]
        print(f"Downloading FSRCNN x{scale} model...")
        tmp_model = model_path.with_suffix(".tmp")
        max_model_bytes = 500 * (1 << 20)  # 500 MiB limit
        req = urllib.request.Request(url)  # noqa: S310
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        with urllib.request.urlopen(req, timeout=120, context=ssl_context) as resp, open(tmp_model, "wb") as fh:  # noqa: S310
            total = 0
            while True:
                chunk = resp.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                total += len(chunk)
                if total > max_model_bytes:
                    tmp_model.unlink(missing_ok=True)
                    raise MCPVideoError(
                        f"Model download exceeded {max_model_bytes >> 20} MiB size limit",
                        error_type="resource_error",
                        code="download_size_limit",
                    )
                fh.write(chunk)
        tmp_model.rename(model_path)
        print(f"Model saved to {model_path}")

    _verify_model_hash(model_path, expected_hash)
    return model_path


def _init_opencv_sr(scale: int, model_path: Path):
    """Initialize OpenCV DNN Super Resolution with FSRCNN.

    Args:
        scale: Upscaling factor.
        model_path: Path to the FSRCNN model file.

    Returns:
        OpenCV DNN Super Resolution object.

    Raises:
        MCPVideoError: If OpenCV was built without dnn_superres module.
    """
    import cv2

    if not hasattr(cv2, "dnn_superres"):
        raise MCPVideoError(
            "OpenCV was built without dnn_superres module. Install opencv-contrib-python for full AI support.",
            error_type="dependency_error",
            code="missing_opencv_contrib",
        )
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(str(model_path))
    sr.setModel("fsrcnn", scale)
    return sr


def _init_realesrgan(model: str, scale: int):
    """Initialize Real-ESRGAN upsampler.

    Args:
        model: Model name ("realesrgan" or "bsrgan").
        scale: Upscaling factor.

    Returns:
        RealESRGANer upsampler instance.
    """
    from realesrgan import RealESRGANer
    from basicsr.archs.rrdbnet_arch import RRDBNet

    model_configs = {
        "realesrgan": {"num_block": 23, "num_feat": 64},
        "bsrgan": {"num_block": 23, "num_feat": 64},
    }
    config = model_configs[model]
    rrdb_net = RRDBNet(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=config["num_feat"],
        num_block=config["num_block"],
        num_grow_ch=32,
        scale=scale,
    )
    return RealESRGANer(
        scale=scale,
        model_path=None,  # Auto-download
        model=rrdb_net,
        tile=256,  # Process in 256x256 tiles to limit memory usage
        tile_pad=10,
        pre_pad=0,
        half=False,  # Use FP32
    )


def _extract_frames(video_path: str, frames_dir: Path) -> list[Path]:
    """Extract frames from video using FFmpeg.

    Args:
        video_path: Input video path.
        frames_dir: Directory to save extracted frames.

    Returns:
        Sorted list of extracted frame paths.
    """
    frame_pattern = frames_dir / "frame_%04d.png"
    _run_command(
        ["ffmpeg", "-y", "-i", video_path, "-vsync", "0", str(frame_pattern)],
        timeout=DEFAULT_FFMPEG_TIMEOUT,
    )
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise ProcessingError("ffmpeg", 1, "No frames extracted from video")
    return frames


def _extract_audio(video_path: str, audio_path: Path) -> bool:
    """Extract audio stream from video to a separate file.

    Args:
        video_path: Input video path.
        audio_path: Output audio file path.

    Returns:
        True if audio was extracted successfully, False otherwise.
    """
    try:
        _run_command(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-c:a", "copy", str(audio_path)],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
        return True
    except ProcessingError:
        return False


def _reconstruct_video(
    frame_pattern: Path,
    output_path: Path,
    fps: float,
    audio_source: str | None = None,
) -> None:
    """Reconstruct video from image sequence using FFmpeg.

    Args:
        frame_pattern: Frame sequence pattern (e.g., frames/frame_%04d.png).
        output_path: Output video path.
        fps: Frame rate for the output video.
        audio_source: Optional audio source path to include.
    """
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frame_pattern)]
    if audio_source:
        cmd.extend(["-i", audio_source, "-c:a", "copy", "-shortest"])
    cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_path)])
    _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)


def _ai_upscale_opencv(video_path: str, output_path: str, scale: int) -> str:
    """AI upscaling fallback using OpenCV DNN Super Resolution.

    Uses lightweight FSRCNN model for fast CPU inference.
    Downloads models automatically on first use.
    """
    import cv2

    model_path = _download_fsrcnn_model(scale)
    sr = _init_opencv_sr(scale, model_path)

    _validate_output_path(output_path)
    output_file = Path(output_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        frames_dir = tmpdir_path / "frames"
        upscaled_dir = tmpdir_path / "upscaled"
        frames_dir.mkdir()
        upscaled_dir.mkdir()

        fps = _get_video_fps(video_path)
        has_audio = _has_audio_stream(video_path)

        frames = _extract_frames(video_path, frames_dir)

        for i, frame_path in enumerate(frames, 1):
            img = cv2.imread(str(frame_path))
            if img is None:
                raise ProcessingError("cv2.imread", 1, f"Failed to load frame: {frame_path}")
            result_img = sr.upsample(img)
            cv2.imwrite(str(upscaled_dir / f"frame_{i:04d}.png"), result_img)

        _reconstruct_video(
            upscaled_dir / "frame_%04d.png",
            output_file,
            fps if fps is not None else 30.0,
            audio_source=video_path if has_audio else None,
        )

    return str(output_file)


def ai_upscale(
    video: str,
    output: str,
    scale: int = 2,
    model: str = "realesrgan",
) -> str:
    """AI-powered video upscaling using Real-ESRGAN.

    Args:
        video: Input video path
        output: Output video path
        scale: Upscaling factor (2 or 4)
        model: Model to use (realesrgan, bsrgan)

    Returns:
        Path to output video

    Raises:
        RuntimeError: If Real-ESRGAN is not installed or processing fails
        FileNotFoundError: If input video doesn't exist
    """
    _validate_input_path(video)

    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)

    if scale not in (2, 4):
        raise MCPVideoError(
            f"Scale must be 2 or 4, got {scale}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    model_configs = {
        "realesrgan": {"num_block": 23, "num_feat": 64},
        "bsrgan": {"num_block": 23, "num_feat": 64},
    }
    if model not in model_configs:
        raise MCPVideoError(
            f"Unknown model: {model}. Choose from: {list(model_configs.keys())}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    _validate_upscale_resource_limits(str(video_path))
    _validate_output_path(output)
    output_path = Path(output)

    # Try to use Real-ESRGAN if available, otherwise use OpenCV DNN fallback
    # NOTE: basicsr <= 1.4.2 has CVE-2024-27763 (command injection via SLURM_NODELIST).
    # Our usage only imports the RRDBNet architecture class for inference.
    # We do not execute the vulnerable scontrol path in basicsr/utils/dist_util.py.
    try:
        import realesrgan  # noqa: F401
        import basicsr.archs.rrdbnet_arch  # noqa: F401

        has_realesrgan = True
    except ImportError:
        has_realesrgan = False

    if not has_realesrgan:
        try:
            return _ai_upscale_opencv(str(video_path), str(output_path), scale)
        except ImportError:
            raise MCPVideoError(
                "AI upscaling requires either realesrgan or opencv-contrib-python (cv2). "
                'Install with: pip install "mcp-video[upscale]" (Python 3.11/3.12)',
                error_type="dependency_error",
                code="missing_upscale_dep",
            ) from None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        frames_dir = tmpdir_path / "frames"
        upscaled_dir = tmpdir_path / "upscaled"
        frames_dir.mkdir()
        upscaled_dir.mkdir()

        fps = _get_video_fps(str(video_path))
        has_audio = _has_audio_stream(str(video_path))

        frames = _extract_frames(str(video_path), frames_dir)
        upsampler = _init_realesrgan(model, scale)

        import numpy as np
        from PIL import Image

        for i, frame_path in enumerate(frames, 1):
            img = Image.open(frame_path).convert("RGB")
            output_img, _ = upsampler.enhance(np.array(img), outscale=scale)
            Image.fromarray(output_img).save(upscaled_dir / f"frame_{i:04d}.png")

        audio_source = None
        if has_audio:
            audio_path = tmpdir_path / "audio.aac"
            if _extract_audio(str(video_path), audio_path):
                audio_source = str(audio_path)

        _reconstruct_video(
            upscaled_dir / "frame_%04d.png",
            output_path,
            fps if fps is not None else 30.0,
            audio_source=audio_source,
        )

    return str(output_path)


def _get_video_fps(video_path: str) -> float | None:
    """Get video frame rate using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)
    except ProcessingError:
        return None

    fps_str = result.stdout.strip()
    if "/" in fps_str:
        num, den = fps_str.split("/")
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    else:
        try:
            return float(fps_str)
        except ValueError:
            return None


def _has_audio_stream(video_path: str) -> bool:
    """Check if video has an audio stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)
    except ProcessingError:
        return False
    return result.returncode == 0 and "audio" in result.stdout.lower()
