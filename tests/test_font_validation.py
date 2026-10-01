"""Structural font admission catches real truncation and hostile table spans."""

from io import BytesIO
from pathlib import Path
import struct

import pytest

from kinocut import font_validation


def sfnt(version=b"\x00\x01\x00\x00", offset=28, length=4, count=1):
    return (
        struct.pack(">4sHHHH", version, count, 16, 0, 0) + struct.pack(">4sIII", b"test", 0, offset, length) + b"data"
    )


@pytest.mark.parametrize("version", [b"\x00\x01\x00\x00", b"OTTO", b"true"])
def test_bounded_sfnt_with_one_table_is_valid_and_preserves_cursor(version):
    stream = BytesIO(sfnt(version))
    stream.seek(7)
    assert font_validation.validate_font_stream(stream)
    assert stream.tell() == 7


@pytest.mark.parametrize("body", [b"", b"OTTO", b"HTML error response", b"\x00\x01\x00\x00" + b"\x00" * 28])
def test_invalid_or_zero_table_container_is_rejected(body):
    assert not font_validation.validate_font_stream(BytesIO(body))


@pytest.mark.parametrize("offset,length", [(28, 5), (33, 0), (0, 4), (12, 4), (0xFFFFFFFF, 4), (28, 0xFFFFFFFF)])
def test_table_span_must_fit_file_and_avoid_its_directory(offset, length):
    assert not font_validation.validate_font_stream(BytesIO(sfnt(offset=offset, length=length)))


@pytest.mark.parametrize("count", [0, 257, 65535])
def test_table_count_is_bounded(count):
    assert not font_validation.validate_font_stream(BytesIO(sfnt(count=count)))


def test_download_size_limit_precedes_parsing(monkeypatch):
    monkeypatch.setattr(font_validation, "MAX_FONT_DOWNLOAD_BYTES", 31)
    assert not font_validation.validate_font_stream(BytesIO(sfnt()))


def collection(version=0x00010000):
    header_size = 20 + (12 if version == 0x00020000 else 0)
    table_offset = header_size + 56
    header = struct.pack(">4sIIII", b"ttcf", version, 2, header_size, header_size + 28)
    if version == 0x00020000:
        header += b"\x00" * 12
    font = sfnt(offset=table_offset)[:-4]
    return header + font + font + b"data"


@pytest.mark.parametrize("version", [0x00010000, 0x00020000])
def test_collection_supports_shared_table_data(version):
    assert font_validation.validate_font_stream(BytesIO(collection(version)))


@pytest.mark.parametrize("start,value", [(4, 3), (8, 0), (8, 65), (12, 0), (16, 20), (16, 0xFFFFFFFF)])
def test_collection_rejects_invalid_versions_counts_and_directory_offsets(start, value):
    body = bytearray(collection())
    body[start : start + 4] = struct.pack(">I", value)
    assert not font_validation.validate_font_stream(BytesIO(body))


def test_collection_rejects_overlapping_font_directories():
    body = bytearray(collection())
    body[16:20] = struct.pack(">I", 24)
    assert not font_validation.validate_font_stream(BytesIO(body))


def test_collection_rejects_table_beyond_end():
    assert not font_validation.validate_font_stream(BytesIO(collection()[:-1]))


def test_collection_v2_signature_must_fit_file():
    body = bytearray(collection(0x00020000))
    body[20:32] = struct.pack(">III", 0x44534947, 4, len(body))
    assert not font_validation.validate_font_stream(BytesIO(body))


def test_unreadable_stream_returns_false():
    stream = BytesIO(sfnt())
    stream.close()
    assert not font_validation.validate_font_stream(stream)


def test_real_installed_font_accepts_complete_file_and_rejects_truncation():
    from kinocut.effects_engine.text import _resolve_font_family_to_file

    path = _resolve_font_family_to_file("Arial")
    if path is None or not Path(path).is_file():
        pytest.skip("No installed font is available")
    with open(path, "rb") as stream:
        assert font_validation.validate_font_stream(stream)
        stream.seek(0)
        truncated = stream.read(1000)
    assert not font_validation.validate_font_stream(BytesIO(truncated))
