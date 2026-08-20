"""Object-matte extra: pin/cache, hole-cut, equipment gate. No weight download."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from mcp_video.errors import MCPVideoError
from mcp_video.hyperframes_engine import remove_background
from mcp_video.object_matte.equipment import apply_equipment_gate, intersection_ratio, static_row_mask
from mcp_video.object_matte.infer import postprocess, preprocess
from mcp_video.object_matte.weights import _copy_capped, _verify_weights, ensure_weights
from mcp_video.validation import OBJECT_MATTE_INPUT_SIZE


def _png(path: Path, color=(20, 80, 160), size=(32, 32)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


class _FakeSession:
    def get_inputs(self):
        return [type("I", (), {"name": "input"})()]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _unused, feeds):
        blob = next(iter(feeds.values()))
        height, width = blob.shape[-2], blob.shape[-1]
        ramp = np.linspace(-3.0, 3.0, height, dtype=np.float32)[:, None] * np.ones((1, width), dtype=np.float32)
        return [ramp[None, None, ...]]


def _missing_extra():
    raise MCPVideoError(
        'Product/object cutouts require pip install "kinocut[object-matte]". Guide: docs/PRODUCT_MATTE.md.',
        error_type="dependency_error",
        code="missing_object_matte",
        docs_url="docs/PRODUCT_MATTE.md",
    )


def test_pyproject_has_object_matte_extra():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    extras = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    deps = extras["object-matte"]
    assert any(item.startswith("onnxruntime") for item in deps)
    assert any(item.startswith("numpy") for item in deps)
    assert any(item.startswith("pillow") for item in deps)


def test_missing_extra_is_dependency_error_and_never_calls_hf(monkeypatch, tmp_path: Path):
    source = _png(tmp_path / "sku.png")
    monkeypatch.setattr("mcp_video.object_matte.api.require_object_matte_deps", _missing_extra)
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background(str(source), model="birefnet-general")
    mock_op.assert_not_called()
    mock_run.assert_not_called()
    assert excinfo.value.error_type == "dependency_error"
    assert "kinocut[object-matte]" in str(excinfo.value)
    assert "Cerafica" not in str(excinfo.value)


def test_hash_mismatch_deletes_file(tmp_path: Path):
    fake = tmp_path / "birefnet-general.onnx"
    fake.write_bytes(b"not-the-pinned-weights" * 64)
    with pytest.raises(MCPVideoError) as excinfo:
        _verify_weights(fake)
    assert excinfo.value.error_type == "integrity_error"
    assert fake.exists() is False


def test_oversize_download_errors(tmp_path: Path):
    handle = BytesIO()

    class _Resp:
        def __init__(self):
            self._chunks = [b"x" * (1 << 20), b"y" * (1 << 20)]

        def read(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

    with (
        patch("mcp_video.object_matte.weights.OBJECT_MATTE_MAX_DOWNLOAD_BYTES", 100),
        pytest.raises(MCPVideoError) as excinfo,
    ):
        _copy_capped(_Resp(), handle)
    assert excinfo.value.code == "download_size_limit"


def test_ensure_weights_cache_hit_skips_download(monkeypatch, tmp_path: Path):
    weights = tmp_path / "birefnet-general.onnx"
    weights.write_bytes(b"cached")
    monkeypatch.setattr("mcp_video.object_matte.weights.object_matte_cache_path", lambda: weights)
    monkeypatch.setattr("mcp_video.object_matte.weights._verify_weights", lambda path: None)
    called = {"download": False}
    monkeypatch.setattr(
        "mcp_video.object_matte.weights._download_weights",
        lambda path: called.__setitem__("download", True),
    )
    path, hit = ensure_weights()
    assert path == weights
    assert hit is True
    assert called["download"] is False


def test_mocked_still_writes_output_and_hole_cut(monkeypatch, tmp_path: Path):
    source = _png(tmp_path / "sku.png")
    out = tmp_path / "sku-cutout.png"
    hole = tmp_path / "sku-hole.png"
    monkeypatch.setattr("mcp_video.object_matte.api.require_object_matte_deps", lambda: None)
    monkeypatch.setattr("mcp_video.object_matte.api.ensure_weights", lambda: (tmp_path / "w.onnx", True))
    monkeypatch.setattr(
        "mcp_video.object_matte.api.make_session",
        lambda _weights, _device: (_FakeSession(), ["CPUExecutionProvider"]),
    )
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
    ):
        result = remove_background(
            str(source),
            output_path=str(out),
            background_output_path=str(hole),
            model="birefnet-general",
            device="auto",
            quality="balanced",
        )
    mock_op.assert_not_called()
    mock_run.assert_not_called()
    data = result.data
    assert data["output"] == str(out)
    assert data["backend"] == "kinocut-onnx"
    assert data["model"] == "birefnet-general"
    assert data["cache_hit"] is True
    assert data["providers"] == ["CPUExecutionProvider"]
    assert "Cerafica" not in str(data)
    assert out.is_file()
    assert hole.is_file()
    cut_alpha = np.asarray(Image.open(out).split()[-1])
    hole_alpha = np.asarray(Image.open(hole).split()[-1])
    assert int(cut_alpha.max()) > 0
    assert np.allclose(cut_alpha.astype(np.int16) + hole_alpha.astype(np.int16), 255, atol=1)


def test_preprocess_shape_and_postprocess_minmax():
    image = Image.new("RGB", (40, 20), (10, 20, 30))
    blob = preprocess(image)
    assert blob.shape == (1, 3, OBJECT_MATTE_INPUT_SIZE, OBJECT_MATTE_INPUT_SIZE)
    mask = postprocess(np.full((1, 1, 8, 8), 4.0, dtype=np.float32), (40, 20))
    assert mask.size == (40, 20)
    assert mask.mode == "L"


def test_equipment_off_succeeds_with_synthetic_intersection(tmp_path: Path):
    subject = Image.fromarray(np.full((20, 20), 255, dtype=np.uint8), mode="L")
    overlay = tmp_path / "equipment.png"
    ratio = apply_equipment_gate(
        subject=subject,
        frames=[Image.new("RGB", (20, 20), 0)],
        overlay_path=str(overlay),
        fail_if_equipment_on_subject=False,
        threshold=0.01,
    )
    assert overlay.is_file()
    assert ratio >= 0.0


def test_equipment_fail_flag_aborts_and_writes_png(tmp_path: Path):
    subject = Image.fromarray(np.full((20, 20), 255, dtype=np.uint8), mode="L")
    overlay = tmp_path / "equipment.png"
    with pytest.raises(MCPVideoError) as excinfo:
        apply_equipment_gate(
            subject=subject,
            frames=[Image.new("RGB", (20, 20), 0)],
            overlay_path=str(overlay),
            fail_if_equipment_on_subject=True,
            threshold=0.01,
        )
    assert overlay.is_file()
    assert excinfo.value.code == "equipment_on_subject"
    assert "turntable" in str(excinfo.value).lower() or "stand" in str(excinfo.value).lower()
    band = static_row_mask((20, 20))
    assert intersection_ratio(subject, band) > 0.01


def test_equipment_fail_without_overlay_path_errors():
    subject = Image.new("L", (8, 8), 255)
    with pytest.raises(MCPVideoError) as excinfo:
        apply_equipment_gate(
            subject=subject,
            frames=[Image.new("RGB", (8, 8))],
            overlay_path=None,
            fail_if_equipment_on_subject=True,
        )
    assert excinfo.value.error_type == "validation_error"


def test_info_still_does_not_download(monkeypatch):
    monkeypatch.setattr(
        "mcp_video.object_matte.weights._download_weights",
        lambda path: (_ for _ in ()).throw(AssertionError("info must not download")),
    )
    result = remove_background(info=True)
    assert result.data["models"]["birefnet-general"]["install"] == 'pip install "kinocut[object-matte]"'
