"""Raw byte digests stay compatible with persisted receipts and identity checks."""

import hashlib

import pytest

from kinocut.errors import MCPVideoError
from kinocut.host_probes import local_digest
from kinocut.rescue import operations
from kinocut.still_plates import io as still_io
from kinocut.te import sphere_probe
from kinocut.visual_intelligence import reframe_render


@pytest.mark.parametrize("data", [b"", b"\x00\xff\xfe", bytes(range(256)) * 2049], ids=["empty", "binary", "large"])
def test_raw_byte_hash_formats_at_receipt_boundaries(tmp_path, data):
    from kinocut.hashing import file_sha256, prefixed_file_sha256

    path = tmp_path / "source.bin"
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    prefixed = "sha256:" + expected
    assert file_sha256(path) == still_io.file_sha256(str(path)) == expected
    assert prefixed_file_sha256(str(path)) == operations._sha256(path) == local_digest(path) == prefixed
    assert sphere_probe._file_sha256(str(path)) == reframe_render._sha256(path) == prefixed


def test_missing_model_digest_is_none_for_directory_or_missing_path(tmp_path):
    assert local_digest(tmp_path) is None
    assert local_digest(tmp_path / "absent") is None


@pytest.mark.parametrize("digest", [sphere_probe._file_sha256, reframe_render._sha256])
def test_identity_sensitive_hash_rejects_changes_while_reading(tmp_path, monkeypatch, digest):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"initial")
    file_digest = hashlib.file_digest

    def hash_then_change(source, algorithm):
        result = file_digest(source, algorithm)
        path.write_bytes(b"different size")
        return result

    monkeypatch.setattr(hashlib, "file_digest", hash_then_change)
    with pytest.raises(MCPVideoError) as raised:
        digest(str(path))
    assert raised.value.code == "source_identity_changed"
