"""Model cache ownership and integrity controls without real downloads."""

import hashlib
from io import BytesIO

import pytest

from kinocut.errors import MCPVideoError
from kinocut.model_cache import model_download_stage
from kinocut.staged_writers import open_staged_writer


@pytest.mark.parametrize("failure", [False, True])
def test_model_stage_preserves_prior_cache_until_verified(tmp_path, failure):
    destination = tmp_path / "model.onnx"
    destination.write_bytes(b"prior")
    foreign = destination.with_suffix(".tmp")
    foreign.write_bytes(b"foreign")
    try:
        with model_download_stage(destination) as stage:
            with open_staged_writer(str(stage)) as output:
                output.write(b"new")
            assert destination.read_bytes() == b"prior"
            if failure:
                raise MCPVideoError("bad integrity")
    except MCPVideoError:
        assert failure
    assert destination.read_bytes() == (b"prior" if failure else b"new")
    assert foreign.read_bytes() == b"foreign"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("payload", [b"pinned", b"wrong!", b"short", b"too-large", None])
def test_object_weights_verify_before_publication(monkeypatch, tmp_path, payload):
    import kinocut.object_matte.weights as weights

    pinned = b"pinned"
    monkeypatch.setattr(weights, "OBJECT_MATTE_WEIGHTS_BYTES", len(pinned))
    monkeypatch.setattr(weights, "OBJECT_MATTE_WEIGHTS_SHA256", hashlib.sha256(pinned).hexdigest())
    monkeypatch.setattr(weights, "OBJECT_MATTE_WEIGHTS_MD5", hashlib.md5(pinned, usedforsecurity=False).hexdigest())
    monkeypatch.setattr(weights, "OBJECT_MATTE_MAX_DOWNLOAD_BYTES", 8)

    def response(*args, **kwargs):
        if payload is None:
            raise OSError("network unavailable")
        return BytesIO(payload)

    monkeypatch.setattr(weights.urllib.request, "urlopen", response)
    destination = tmp_path / "model.onnx"
    destination.write_bytes(b"prior")
    foreign = destination.with_suffix(".tmp")
    foreign.write_bytes(b"foreign")
    if payload == pinned:
        weights._download_weights(destination)
        assert destination.read_bytes() == pinned
    else:
        with pytest.raises((MCPVideoError, OSError)):
            weights._download_weights(destination)
        assert destination.read_bytes() == b"prior"
    assert foreign.read_bytes() == b"foreign"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("valid", [False, True])
def test_fsrcnn_verifies_before_publication(monkeypatch, tmp_path, valid):
    import urllib.request

    import kinocut.ai_engine.upscale as upscale

    pinned = b"pinned"
    monkeypatch.setattr(upscale.Path, "home", lambda: tmp_path)
    monkeypatch.setitem(upscale._MODEL_HASHES, "FSRCNN_x2.pb", hashlib.sha256(pinned).hexdigest())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: BytesIO(pinned if valid else b"wrong"))
    directory = tmp_path / ".cache" / "mcp-video" / "models"
    directory.mkdir(parents=True)
    foreign = directory / "FSRCNN_x2.tmp"
    foreign.write_bytes(b"foreign")
    destination = directory / "FSRCNN_x2.pb"
    if valid:
        assert upscale._download_fsrcnn_model(2) == destination
        assert destination.read_bytes() == pinned
    else:
        with pytest.raises(MCPVideoError, match="integrity"):
            upscale._download_fsrcnn_model(2)
        assert not destination.exists()
    assert foreign.read_bytes() == b"foreign"
    assert not list(directory.glob(".kinocut_tmp_*"))
