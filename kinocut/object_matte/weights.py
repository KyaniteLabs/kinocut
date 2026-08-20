"""Pinned birefnet-general ONNX cache (FSRCNN-style hash + size cap)."""

from __future__ import annotations

import hashlib
import ssl
import urllib.request
from pathlib import Path

from ..defaults import DEFAULT_OBJECT_MATTE_TIMEOUT
from ..errors import MCPVideoError
from ..validation import (
    OBJECT_MATTE_MAX_DOWNLOAD_BYTES,
    OBJECT_MATTE_WEIGHTS_BYTES,
    OBJECT_MATTE_WEIGHTS_MD5,
    OBJECT_MATTE_WEIGHTS_SHA256,
    OBJECT_MATTE_WEIGHTS_URL,
    object_matte_cache_path,
)

_DOCS = "docs/PRODUCT_MATTE.md"


def _digest_file(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _verify_weights(path: Path) -> None:
    size = path.stat().st_size
    if size != OBJECT_MATTE_WEIGHTS_BYTES:
        path.unlink(missing_ok=True)
        raise MCPVideoError(
            f"Object-matte weights size mismatch for {path.name}: "
            f"expected {OBJECT_MATTE_WEIGHTS_BYTES}, got {size}. File deleted.",
            error_type="integrity_error",
            code="model_size_mismatch",
            docs_url=_DOCS,
        )
    sha, md5 = _digest_file(path)
    if sha != OBJECT_MATTE_WEIGHTS_SHA256 or md5 != OBJECT_MATTE_WEIGHTS_MD5:
        path.unlink(missing_ok=True)
        raise MCPVideoError(
            f"Object-matte weights integrity check failed for {path.name}. File deleted.",
            error_type="integrity_error",
            code="model_hash_mismatch",
            docs_url=_DOCS,
        )


def _download_weights(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    req = urllib.request.Request(OBJECT_MATTE_WEIGHTS_URL)  # noqa: S310
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    try:
        with (
            urllib.request.urlopen(  # noqa: S310
                req, timeout=DEFAULT_OBJECT_MATTE_TIMEOUT, context=context
            ) as resp,
            tmp_path.open("wb") as handle,
        ):
            _copy_capped(resp, handle)
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _copy_capped(resp: object, handle: object) -> None:
    total = 0
    while True:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if total > OBJECT_MATTE_MAX_DOWNLOAD_BYTES:
            raise MCPVideoError(
                "Object-matte download exceeded 1 GiB size limit. Partial file deleted.",
                error_type="resource_error",
                code="download_size_limit",
                docs_url=_DOCS,
            )
        handle.write(chunk)


def ensure_weights() -> tuple[Path, bool]:
    """Return (cache path, cache_hit). Never called by doctor or --info."""
    path = object_matte_cache_path()
    cache_hit = path.is_file()
    if cache_hit:
        _verify_weights(path)
        return path, True
    _download_weights(path)
    _verify_weights(path)
    return path, False
