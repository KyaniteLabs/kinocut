"""Bounded structural validation of downloaded SFNT fonts and collections.

Checks declared table extents before publication or cached reuse. This is a
container integrity check, not a glyph renderer or a font authenticity claim.
"""

from __future__ import annotations

import contextlib
import os
import struct
from typing import BinaryIO
from itertools import pairwise

from .limits import MAX_FONT_COLLECTION_FONTS, MAX_FONT_DOWNLOAD_BYTES, MAX_FONT_TABLES

_SFNT_VERSIONS = (b"\x00\x01\x00\x00", b"OTTO", b"true")
_COLLECTION_VERSIONS = (0x00010000, 0x00020000)
_INVALID_STREAM = (AttributeError, OSError, OverflowError, struct.error, TypeError, ValueError)


def validate_font_stream(stream: BinaryIO) -> bool:
    """Validate a seekable binary stream without loading the font into memory.

    Restore its original cursor; malformed, truncated, oversized or unreadable
    containers return False. Shared table data in a collection is supported.
    """
    position = None
    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if not 12 <= size <= MAX_FONT_DOWNLOAD_BYTES:
            return False
        stream.seek(0)
        signature = stream.read(4)
        if signature == b"ttcf":
            return _validate_collection(stream, size)
        if signature not in _SFNT_VERSIONS:
            return False
        directory = _font_directory(stream, 0, size)
        return directory is not None and _validate_tables(stream, directory, size, [directory], 0)
    except _INVALID_STREAM:
        return False
    finally:
        if position is not None:
            with contextlib.suppress(_INVALID_STREAM):
                stream.seek(position)


def _font_directory(stream: BinaryIO, offset: int, size: int) -> tuple[int, int] | None:
    if offset < 0 or offset + 12 > size:
        return None
    stream.seek(offset)
    version, count = struct.unpack(">4sH", stream.read(6))
    if version not in _SFNT_VERSIONS or not 1 <= count <= MAX_FONT_TABLES:
        return None
    end = offset + 12 + count * 16
    return (offset, end) if end <= size else None


def _validate_tables(
    stream: BinaryIO,
    directory: tuple[int, int],
    size: int,
    directories: list[tuple[int, int]],
    collection_header_end: int,
) -> bool:
    start, end = directory
    stream.seek(start + 12)
    for _ in range((end - start - 12) // 16):
        _, _, offset, length = struct.unpack(">4sIII", stream.read(16))
        if offset < collection_header_end or offset > size or length > size - offset:
            return False
        if length and any(
            offset < header_end and offset + length > header_start for header_start, header_end in directories
        ):
            return False
    return True


def _validate_collection(stream: BinaryIO, size: int) -> bool:
    version, count = struct.unpack(">II", stream.read(8))
    if version not in _COLLECTION_VERSIONS or not 1 <= count <= MAX_FONT_COLLECTION_FONTS:
        return False
    header_end = 12 + count * 4 + (12 if version == 0x00020000 else 0)
    if header_end > size:
        return False
    offsets = struct.unpack(f">{count}I", stream.read(count * 4))
    if len(set(offsets)) != count or any(offset < header_end for offset in offsets):
        return False
    if version == 0x00020000:
        tag, length, offset = struct.unpack(">III", stream.read(12))
        if tag and (tag != 0x44534947 or offset < header_end or offset > size or length > size - offset):
            return False
        if not tag and (length or offset):
            return False
    directories = [_font_directory(stream, offset, size) for offset in offsets]
    if any(directory is None for directory in directories):
        return False
    ordered = sorted(directories)
    if any(previous[1] > current[0] for previous, current in pairwise(ordered)):
        return False
    return all(_validate_tables(stream, directory, size, directories, header_end) for directory in directories)
