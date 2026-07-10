"""SoundFile integration — high-quality audio I/O.

License: BSD-3-Clause (https://github.com/bastibe/python-soundfile)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...errors import MCPVideoError


def _require_soundfile() -> Any:
    """Lazy import soundfile with helpful error."""
    try:
        import soundfile as sf

        return sf
    except ImportError as exc:
        raise MCPVideoError(
            "soundfile not installed. Run: pip install soundfile",
            error_type="dependency_error",
            code="soundfile_not_found",
        ) from exc


def read_audio(
    path: str,
    dtype: str = "float64",
    always_2d: bool = False,
) -> dict[str, Any]:
    """Read an audio file using SoundFile.

    Args:
        path: Audio file path
        dtype: Data type for samples
        always_2d: Always return 2D array even for mono

    Returns:
        Dict with samples array, sample_rate, channels
    """
    sf = _require_soundfile()

    path_obj = Path(path)
    if not path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {path}", error_type="input_error", code="invalid_input")

    data, sample_rate = sf.read(path, dtype=dtype, always_2d=always_2d)

    return {
        "samples": data,
        "sample_rate": sample_rate,
        "channels": data.shape[1] if data.ndim > 1 else 1,
        "duration": len(data) / sample_rate,
    }


def write_audio(
    path: str,
    samples: Any,
    sample_rate: int,
    subtype: str = "PCM_16",
) -> str:
    """Write audio samples to a file using SoundFile.

    Supports many formats: WAV, FLAC, OGG, AIFF, etc.

    Args:
        path: Output file path
        samples: Audio samples array
        sample_rate: Sample rate
        subtype: SoundFile subtype (PCM_16, PCM_24, FLOAT, etc.)

    Returns:
        Path to output file
    """
    sf = _require_soundfile()

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, sample_rate, subtype=subtype)
    return path


def resample(
    input_path: str,
    output_path: str,
    target_sample_rate: int,
) -> str:
    """Resample an audio file to a target sample rate.

    Args:
        input_path: Input audio file
        output_path: Output audio file
        target_sample_rate: Target sample rate

    Returns:
        Path to output file
    """
    info = read_audio(input_path)
    samples = info["samples"]
    source_rate = info["sample_rate"]

    if source_rate == target_sample_rate:
        # Just copy
        import shutil

        shutil.copy(input_path, output_path)
        return output_path

    try:
        import numpy as np
        import scipy.signal as signal

        # Calculate resampling ratio
        gcd = np.gcd(source_rate, target_sample_rate)
        up = target_sample_rate // gcd
        down = source_rate // gcd

        if samples.ndim == 2:
            resampled = signal.resample_poly(samples, up, down, axis=0)
        else:
            resampled = signal.resample_poly(samples, up, down)

        write_audio(output_path, resampled, target_sample_rate)
        return output_path
    except ImportError as e:
        raise MCPVideoError(
            "Resampling requires numpy and scipy",
            error_type="dependency_error",
            code="resample_deps_missing",
        ) from e
