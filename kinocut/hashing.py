"""SHA-256 digests of file bytes, independent of receipt serialization."""

import hashlib
from pathlib import Path
from typing import BinaryIO


def stream_sha256(source: BinaryIO) -> str:
    """Hash an open binary file from its current position."""
    return hashlib.file_digest(source, "sha256").hexdigest()


def file_sha256(path: str | Path) -> str:
    """Return the lowercase hex digest of a file's contents."""
    with open(path, "rb") as source:
        return stream_sha256(source)


def prefixed_file_sha256(path: str | Path) -> str:
    return "sha256:" + file_sha256(path)
