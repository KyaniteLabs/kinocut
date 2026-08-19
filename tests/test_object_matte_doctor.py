"""Doctor check for product/object matte. Never downloads weights."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mcp_video.doctor import _check_object_matte, _object_matte_cache_path, run_diagnostics
from mcp_video.validation import OBJECT_MATTE_WEIGHTS_SHA256


def test_object_matte_check_not_ready_without_extra_or_cache(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "birefnet-general.onnx"
    monkeypatch.setattr("mcp_video.doctor._object_matte_cache_path", lambda: missing)
    check = _check_object_matte(find_spec=lambda name: None)
    assert check["name"] == "object_matte"
    assert check["required"] is False
    assert check["ok"] is False
    assert check["details"]["onnxruntime"] is False
    assert check["details"]["weightsCached"] is False
    assert check["details"]["sha256"] is None
    assert check["details"]["sha256Match"] is False
    assert check["details"]["expectedSha256"] == OBJECT_MATTE_WEIGHTS_SHA256
    assert check["details"]["docs"] == "docs/PRODUCT_MATTE.md"
    assert "kinocut[object-matte]" in (check["install_hint"] or "")


def test_object_matte_check_ready_when_runtime_and_hash_match(monkeypatch, tmp_path: Path) -> None:
    weights = tmp_path / "birefnet-general.onnx"
    payload = b"fake-object-matte-weights"
    weights.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr("mcp_video.doctor._object_matte_cache_path", lambda: weights)
    monkeypatch.setattr("mcp_video.validation.OBJECT_MATTE_WEIGHTS_SHA256", digest)
    check = _check_object_matte(find_spec=lambda name: object() if name == "onnxruntime" else None)
    assert check["ok"] is True
    assert check["details"]["weightsCached"] is True
    assert check["details"]["sha256"] == digest
    assert check["details"]["sha256Match"] is True
    assert check["path"] == str(weights)
    assert check["install_hint"] is None


def test_object_matte_check_hash_mismatch_is_not_ready(monkeypatch, tmp_path: Path) -> None:
    weights = tmp_path / "birefnet-general.onnx"
    weights.write_bytes(b"wrong-bytes")
    monkeypatch.setattr("mcp_video.doctor._object_matte_cache_path", lambda: weights)
    check = _check_object_matte(find_spec=lambda name: object() if name == "onnxruntime" else None)
    assert check["ok"] is False
    assert check["details"]["sha256Match"] is False
    assert check["details"]["sha256"] != OBJECT_MATTE_WEIGHTS_SHA256


def test_run_diagnostics_includes_optional_object_matte_check() -> None:
    report = run_diagnostics(
        which=lambda name: None,
        version_runner=lambda command: None,
        find_spec=lambda name: None,
    )
    checks = {check["name"]: check for check in report["checks"]}
    assert "object_matte" in checks
    assert checks["object_matte"]["required"] is False
    assert report["success"] is True


def test_object_matte_cache_path_is_local_models_dir() -> None:
    path = _object_matte_cache_path()
    assert path.name == "birefnet-general.onnx"
    assert "mcp-video" in path.parts
