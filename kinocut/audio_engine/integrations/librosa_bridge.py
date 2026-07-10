"""Librosa integration — audio analysis and feature extraction.

License: BSD-3-Clause (https://github.com/librosa/librosa)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...errors import MCPVideoError


def _require_librosa() -> Any:
    """Lazy import librosa with helpful error."""
    try:
        import librosa

        return librosa
    except ImportError as exc:
        raise MCPVideoError(
            "librosa not installed. Run: pip install librosa",
            error_type="dependency_error",
            code="librosa_not_found",
        ) from exc


def analyze_audio(
    path: str,
    sample_rate: int | None = None,
) -> dict[str, Any]:
    """Analyze an audio file and return key features.

    Args:
        path: Audio file path
        sample_rate: Target sample rate (None = native)

    Returns:
        Dict with tempo, key, duration, RMS energy, spectral centroid
    """
    librosa = _require_librosa()
    import numpy as np

    path_obj = Path(path)
    if not path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {path}", error_type="input_error", code="invalid_input")

    y, sr = librosa.load(path, sr=sample_rate)

    # Tempo
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)

    # Key detection
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = np.mean(chroma, axis=1)
    key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    estimated_key = key_names[int(np.argmax(chroma_mean))]

    # RMS energy
    rms = librosa.feature.rms(y=y)[0]
    mean_rms = float(np.mean(rms))

    # Spectral centroid
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    mean_centroid = float(np.mean(centroid))

    # Zero crossing rate
    zcr = librosa.feature.zero_crossing_rate(y)[0]
    mean_zcr = float(np.mean(zcr))

    return {
        "path": path,
        "sample_rate": sr,
        "duration": float(librosa.get_duration(y=y, sr=sr)),
        "tempo_bpm": float(tempo),
        "estimated_key": estimated_key,
        "mean_rms": mean_rms,
        "mean_spectral_centroid_hz": mean_centroid,
        "mean_zero_crossing_rate": mean_zcr,
    }


def extract_beats(
    path: str,
    sample_rate: int | None = None,
) -> dict[str, Any]:
    """Extract beat frames and times from an audio file.

    Args:
        path: Audio file path
        sample_rate: Target sample rate

    Returns:
        Dict with beat_times, beat_frames, tempo
    """
    librosa = _require_librosa()

    path_obj = Path(path)
    if not path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {path}", error_type="input_error", code="invalid_input")

    y, sr = librosa.load(path, sr=sample_rate)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    return {
        "path": path,
        "tempo_bpm": float(tempo),
        "beat_times": beat_times.tolist(),
        "beat_frames": beat_frames.tolist(),
    }


def extract_mfcc(
    path: str,
    n_mfcc: int = 13,
    sample_rate: int | None = None,
) -> dict[str, Any]:
    """Extract MFCC features from an audio file.

    Args:
        path: Audio file path
        n_mfcc: Number of MFCC coefficients
        sample_rate: Target sample rate

    Returns:
        Dict with mfcc array, sample_rate
    """
    librosa = _require_librosa()
    import numpy as np

    path_obj = Path(path)
    if not path_obj.exists():
        raise MCPVideoError(f"Audio file not found: {path}", error_type="input_error", code="invalid_input")

    y, sr = librosa.load(path, sr=sample_rate)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)

    return {
        "path": path,
        "sample_rate": sr,
        "n_mfcc": n_mfcc,
        "mfcc_mean": np.mean(mfcc, axis=1).tolist(),
        "mfcc_std": np.std(mfcc, axis=1).tolist(),
    }
