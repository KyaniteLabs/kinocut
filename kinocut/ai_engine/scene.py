"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _run_command, _run_ffprobe_json, _validate_input_path
from ..limits import DEFAULT_FFMPEG_TIMEOUT, MAX_AI_SCENE_FRAMES, MAX_VIDEO_DURATION
from .spatial import _standard_scene_detect

logger = logging.getLogger(__name__)


def _validate_scene_threshold(threshold: float) -> float:
    if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(
            f"threshold must be between 0.0 and 1.0, got {threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return float(threshold)


def _parse_duration(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def ai_scene_detect(
    video: str,
    threshold: float = 0.3,
    use_ai: bool = False,
) -> list[dict]:
    """ML-enhanced scene detection using perceptual hashing.

    Args:
        video: Input video path
        threshold: Scene change threshold (for standard mode)
        use_ai: If True, use perceptual hashing for better accuracy

    Returns:
        List of scene changes with timestamps and frame numbers
    """
    threshold = _validate_scene_threshold(threshold)
    if not use_ai:
        # Standard FFmpeg scene detection
        return _standard_scene_detect(video, threshold)

    # AI-enhanced: Use perceptual hashing
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        # Fall back to standard detection
        return _standard_scene_detect(video, threshold)

    _validate_input_path(video)
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)

    # Step 1: Get video duration and frame rate
    info = _run_ffprobe_json(str(video_path))
    duration = _parse_duration(info.get("format", {}).get("duration", 0))

    if duration == 0:
        return []
    if duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds maximum of {MAX_VIDEO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )

    # Step 2: Extract frames at a bounded interval.
    frame_interval = max(0.5, duration / MAX_AI_SCENE_FRAMES)
    scenes = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract frames at regular intervals
        frame_pattern = Path(tmpdir) / "frame_%04d.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-vf",
            f"fps=1/{frame_interval},scale=320:-1",
            "-q:v",
            "2",
            str(frame_pattern).replace("%04d", "%04d"),
        ]
        try:
            _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)
        except ProcessingError:
            # Fall back to standard detection on error
            return _standard_scene_detect(video, threshold)

        # Get all extracted frames sorted by time
        frames = sorted(Path(tmpdir).glob("frame_*.jpg"))
        if len(frames) < 2:
            return []

        # Step 3: Compute perceptual hash for each frame
        hashes = []
        for frame_path in frames:
            try:
                img = Image.open(frame_path)
                phash = imagehash.phash(img)
                # Extract timestamp from frame number
                # frame_0001.jpg corresponds to 0.0s, frame_0002.jpg to 0.5s, etc.
                frame_num = int(frame_path.stem.split("_")[1])
                timestamp = (frame_num - 1) * frame_interval
                hashes.append({"timestamp": timestamp, "hash": phash, "path": frame_path})
            except Exception as exc:
                logger.debug("Frame hash extraction failed for %s: %s", frame_path, exc)
                continue

        # Step 4: Compare hashes to find significant changes
        # Perceptual hash threshold (lower = more sensitive)
        hash_threshold = 10  # Adjust based on testing

        for i in range(1, len(hashes)):
            prev_hash = hashes[i - 1]["hash"]
            curr_hash = hashes[i]["hash"]

            # Calculate hash difference
            hash_diff = prev_hash - curr_hash

            if hash_diff > hash_threshold:
                scenes.append({"timestamp": float(hashes[i]["timestamp"]), "frame": None, "hash_diff": int(hash_diff)})

    return scenes


# ---------------------------------------------------------------------------
# Silence Detection and Removal
# ---------------------------------------------------------------------------
