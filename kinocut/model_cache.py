"""Owned staging for integrity-verified model cache downloads."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from .atomic_publication import anchored_output
from .ffmpeg_helpers import _validate_write_path


def _validate_model_path(path: str) -> str:
    return _validate_write_path(path, allowed_existing_suffixes=frozenset({".onnx", ".pb"}), label="Model cache path")


@contextmanager
def model_download_stage(destination: Path):
    """Publish only the owned staging inode after the caller verifies it."""
    with anchored_output(str(destination), _validate_model_path) as stage:
        yield Path(stage)
