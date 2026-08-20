"""Object-matte extra: pin/cache, stream/scratch (#412), equipment (#464). No weight download."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from mcp_video.defaults import DEFAULT_OBJECT_MATTE_TIMEOUT
from mcp_video.errors import BackendUnavailableError, MCPVideoError
from mcp_video.hyperframes_engine import remove_background
from mcp_video.limits import MAX_OBJECT_MATTE_FRAMES
from mcp_video.object_matte.encode import assert_alpha_output, write_alpha_video
from mcp_video.object_matte.equipment import apply_equipment_gate, intersection_ratio, static_row_mask
from mcp_video.object_matte.infer import postprocess, preprocess
from mcp_video.object_matte.media import (
    _parse_rate,
    apply_alpha,
    charge_scratch,
    decode_video_argv,
    estimate_scratch_bytes,
    iter_video_rgb,
    refuse_overlong_video,
)
from mcp_video.object_matte.runtime import providers_for_device
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
    assert data["backgroundOutput"] == str(hole)
    assert "Cerafica" not in str(data)
    assert out.is_file()
    assert hole.is_file()
    cut_alpha = np.asarray(Image.open(out).split()[-1])
    hole_alpha = np.asarray(Image.open(hole).split()[-1])
    assert int(cut_alpha.max()) > 0
    assert np.allclose(cut_alpha.astype(np.int16) + hole_alpha.astype(np.int16), 255, atol=1)


def test_preprocess_shape_and_postprocess_minmax():
    from mcp_video.defaults import OBJECT_MATTE_IMAGENET_MEAN, OBJECT_MATTE_IMAGENET_STD

    image = Image.new("RGB", (40, 20), (128, 128, 128))
    blob = preprocess(image)
    assert blob.shape == (1, 3, OBJECT_MATTE_INPUT_SIZE, OBJECT_MATTE_INPUT_SIZE)
    expected = np.array(
        [
            (128 / 255.0 - mean) / std
            for mean, std in zip(OBJECT_MATTE_IMAGENET_MEAN, OBJECT_MATTE_IMAGENET_STD, strict=True)
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(blob[0, :, 0, 0], expected, rtol=1e-5, atol=1e-5)
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


def test_assert_alpha_output_rejects_mp4() -> None:
    with pytest.raises(MCPVideoError) as excinfo:
        assert_alpha_output("sku.mp4")
    assert excinfo.value.error_type == "validation_error"


def test_apply_alpha_invert_is_complement() -> None:
    rgb = Image.new("RGB", (1, 1), (10, 20, 30))
    mask = Image.new("L", (1, 1), 40)
    cut = apply_alpha(rgb, mask, invert=False)
    hole = apply_alpha(rgb, mask, invert=True)
    assert cut.getpixel((0, 0))[3] == 40
    assert hole.getpixel((0, 0))[3] == 215


def test_coreml_missing_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI installs kinocut[dev] only — object-matte/onnxruntime is optional.
    # Stub the module so this guard is covered without the extra.
    import sys
    import types

    fake = types.ModuleType("onnxruntime")
    fake.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    with pytest.raises(BackendUnavailableError):
        providers_for_device("coreml")


def test_mp4_is_rejected_before_weight_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "turn.mp4"
    src.write_bytes(b"not-a-real-mp4")
    dest = tmp_path / "out.mp4"
    monkeypatch.setattr("mcp_video.object_matte.api.require_object_matte_deps", lambda: None)
    with (
        patch("mcp_video.object_matte.api.ensure_weights") as mock_weights,
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background(str(src), output_path=str(dest), model="birefnet-general")
    mock_weights.assert_not_called()
    mock_op.assert_not_called()
    assert excinfo.value.error_type == "validation_error"


def test_decode_argv_caps_rawvideo_pipe() -> None:
    cmd = decode_video_argv("turn.mp4", 8, 8)
    assert "-frames:v" in cmd
    assert str(MAX_OBJECT_MATTE_FRAMES + 1) in cmd
    assert "rawvideo" in cmd
    assert "rgb24" in cmd
    assert "pipe:1" in cmd
    assert not any(part.endswith(".png") for part in cmd)


def test_scratch_budget_aborts_before_unbounded_sequence() -> None:
    with pytest.raises(MCPVideoError) as excinfo:
        charge_scratch(0, 65, cap=64)
    assert excinfo.value.code == "scratch_budget_exceeded"
    assert charge_scratch(10, 20, cap=64) == 30
    assert estimate_scratch_bytes(2, 2, 3, hole=True) == 2 * 2 * 4 * 3 * 2


def test_run_object_matte_scratch_cap_stops_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _png(tmp_path / "sku.png", size=(32, 32))
    dest = tmp_path / "sku-cutout.webm"
    writes: list[str] = []
    original_save = Image.Image.save

    def _spy_save(self, fp, *args, **kwargs):
        writes.append(str(fp))
        return original_save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _spy_save)
    monkeypatch.setattr("mcp_video.object_matte.media.MAX_OBJECT_MATTE_SCRATCH_BYTES", 1)
    monkeypatch.setattr("mcp_video.object_matte.api.require_object_matte_deps", lambda: None)
    monkeypatch.setattr(
        "mcp_video.object_matte.api.ensure_weights",
        lambda: (tmp_path / "w.onnx", True),
    )
    monkeypatch.setattr(
        "mcp_video.object_matte.api.make_session",
        lambda _weights, _device: (_FakeSession(), ["CPUExecutionProvider"]),
    )
    with (
        patch("mcp_video.object_matte.encode.write_alpha_video") as mock_encode,
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background(str(src), output_path=str(dest), model="birefnet-general")
    mock_op.assert_not_called()
    mock_encode.assert_not_called()
    assert excinfo.value.code == "scratch_budget_exceeded"
    assert writes == []


def test_refuse_overlong_video_before_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcp_video.object_matte.media._probe_video_meta",
        lambda _path: (30.0, MAX_OBJECT_MATTE_FRAMES + 1, 8, 8),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        refuse_overlong_video("turn.mp4")
    assert excinfo.value.code == "frame_count_too_large"


def test_unknown_frame_count_refuses_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcp_video.object_matte.media._probe_video_meta",
        lambda _path: (30.0, None, 8, 8),
    )
    started: list[str] = []
    monkeypatch.setattr(
        "mcp_video.object_matte.media.iter_video_rgb",
        lambda *a, **k: started.append("decode") or iter(()),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        refuse_overlong_video("turn.mp4")
    assert excinfo.value.code == "frame_count_unknown"
    assert started == []


def test_stalled_decode_raises_timeout_and_reaps(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[str] = []

    class _Proc:
        stdout = object()
        stderr = None

        def poll(self):
            return None if not killed else -9

        def kill(self):
            killed.append("kill")

        def wait(self, timeout=None):
            return -9

    monkeypatch.setattr("mcp_video.object_matte.media.subprocess.Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr("mcp_video.object_matte.media.select.select", lambda *_a, **_k: ([], [], []))
    with pytest.raises(MCPVideoError) as excinfo:
        list(iter_video_rgb("turn.mp4", 2, 2, deadline=0))
    assert excinfo.value.code == "object_matte_timeout"
    assert killed == ["kill"]


def test_parse_rate_rejects_zero_denominators() -> None:
    assert _parse_rate("0/0") is None
    assert _parse_rate("0/1") is None
    assert _parse_rate("30/1") == 30.0


def test_write_alpha_video_webm_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame_dir = tmp_path / "cut"
    frame_dir.mkdir()
    Image.new("RGBA", (2, 2)).save(frame_dir / "cut_000001.png")
    dest = tmp_path / "out.webm"
    seen: list[tuple[list[str], int | None]] = []

    def _fake_run(cmd: list[str], **kwargs):
        seen.append((cmd, kwargs.get("timeout")))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("mcp_video.object_matte.encode._run_command", _fake_run)
    write_alpha_video(frame_dir, str(dest), 30.0, "cut_%06d.png")
    cmd, timeout = seen[0]
    assert "libvpx-vp9" in cmd
    assert "yuva420p" in cmd
    assert "-auto-alt-ref" in cmd
    assert timeout == DEFAULT_OBJECT_MATTE_TIMEOUT


def test_write_alpha_video_mov_uses_prores_4444(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame_dir = tmp_path / "cut"
    frame_dir.mkdir()
    Image.new("RGBA", (2, 2)).save(frame_dir / "cut_000001.png")
    dest = tmp_path / "out.mov"
    seen: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs):
        seen.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("mcp_video.object_matte.encode._run_command", _fake_run)
    write_alpha_video(frame_dir, str(dest), 24.0, "cut_%06d.png")
    assert "-profile:v" in seen[0]
    assert "4444" in seen[0]
    assert "prores_ks" in seen[0]
