"""Deterministic replay identity and distinct matte outputs before model/inference."""

from pathlib import Path
import os

from PIL import Image
import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _reset_operation_inputs
from kinocut.object_matte import api as matte
from kinocut.visual_intelligence import reframe_render
from tests.test_reframe_render_receipts import _plan, _source


@pytest.fixture(autouse=True)
def isolated_operation():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


@pytest.mark.parametrize("alias", ["same", "canonical", "hardlink"])
def test_matte_output_alias_rejected_before_weights_or_inference(tmp_path, monkeypatch, alias):
    source, cut, hole = tmp_path / "source.png", tmp_path / "cut.png", tmp_path / "hole.png"
    Image.new("RGB", (4, 4), "red").save(source)
    Image.new("RGBA", (4, 4), "green").save(cut)
    if alias == "hardlink":
        os.link(cut, hole)
    else:
        hole = cut if alias == "same" else Path(str(tmp_path) + "/./cut.png")
    original = cut.read_bytes()
    monkeypatch.setattr(matte, "require_object_matte_deps", lambda: None)
    monkeypatch.setattr(
        matte, "ensure_weights", lambda: pytest.fail("Aliases must fail before loading/downloading weights")
    )
    monkeypatch.setattr(matte, "make_session", lambda *args: pytest.fail("Aliases must fail before model inference"))
    with pytest.raises(MCPVideoError) as error:
        matte.run_object_matte(input_path=str(source), output_path=str(cut), background_output_path=str(hole))
    assert error.value.code == "invalid_output_path"
    assert cut.read_bytes() == original


def test_direct_matte_writer_rejects_alias_before_first_image(tmp_path):
    target = tmp_path / "cut.png"
    with pytest.raises(MCPVideoError) as error:
        matte._write_outputs(
            dest=str(target),
            hole=str(target),
            first_cut=Image.new("RGBA", (4, 4), "red"),
            first_hole=Image.new("RGBA", (4, 4), "blue"),
            cut_dir=tmp_path,
            hole_dir=tmp_path,
            fps=30,
            count=1,
        )
    assert error.value.code == "invalid_output_path"
    assert not target.exists()


@pytest.mark.parametrize("existing", ["neither", "cut", "hole", "both"])
def test_distinct_matte_outputs_remain_valid_with_any_existing_path_combination(tmp_path, existing):
    cut, hole = tmp_path / "cut.png", tmp_path / "hole.png"
    if existing in {"cut", "both"}:
        cut.write_bytes(b"original-cut")
    if existing in {"hole", "both"}:
        hole.write_bytes(b"original-hole")
    matte._validate_output_pair(str(cut), str(hole))


def test_reframe_rejects_stale_source_before_any_render_and_preserves_delivery(tmp_path, monkeypatch):
    source, output = tmp_path / "source.mp4", tmp_path / "delivered.mp4"
    _source(source, (50, 500))
    plan = _plan(source, (50, 500))
    _reset_operation_inputs()
    _source(source, (110, 470))
    output.write_bytes(b"prior-delivery")
    monkeypatch.setattr(
        reframe_render, "_run_ffmpeg", lambda *args: pytest.fail("Unreviewed source replacement was rendered")
    )
    with pytest.raises(MCPVideoError) as error:
        reframe_render.render_reframe_plan(str(source), str(output), plan, "portrait")
    assert error.value.code == "source_identity_changed"
    assert output.read_bytes() == b"prior-delivery"


def test_reframe_source_change_during_render_or_output_hash_failure_cannot_publish(tmp_path, monkeypatch):
    source, output = tmp_path / "source.mp4", tmp_path / "delivered.mp4"
    _source(source, (50, 500))
    plan = _plan(source, (50, 500))
    output.write_bytes(b"prior-delivery")

    def render(cmd):
        Path(cmd[-1]).write_bytes(b"encoded")
        source.write_bytes(b"replacement")

    monkeypatch.setattr(reframe_render, "_run_ffmpeg", render)
    monkeypatch.setattr(reframe_render, "probe", lambda *args: None)
    with pytest.raises(MCPVideoError) as error:
        reframe_render.render_reframe_plan(str(source), str(output), plan, "portrait")
    assert error.value.code == "source_identity_changed"
    assert output.read_bytes() == b"prior-delivery"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
