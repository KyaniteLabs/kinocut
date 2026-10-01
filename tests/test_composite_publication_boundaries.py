"""Media and receipt publication must preserve separate, valid artifacts."""

import hashlib
import json
import os
import shutil

import pytest

from kinocut.engine_composite_layers import composite_layers
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _reset_operation_inputs


@pytest.fixture(autouse=True)
def fresh_paths():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _spec(tmp_path):
    path = tmp_path / "layers.json"
    path.write_text(
        json.dumps(
            {
                "canvas": {"width": 160, "height": 90, "fps": 25, "duration": 0.2},
                "layers": [{"id": "blue", "type": "solid", "color": "#0000ff"}],
            }
        )
    )
    return path


@pytest.mark.parametrize("suffix", ["png", "mp4"])
def test_media_receipt_alias_is_rejected_before_render(tmp_path, monkeypatch, suffix):
    output = tmp_path / f"out.{suffix}"
    output.write_bytes(b"prior delivery")
    monkeypatch.setattr("kinocut.engine_composite_layers._run_ffmpeg", lambda _: pytest.fail("must not render"))
    with pytest.raises(MCPVideoError, match="aliases"):
        composite_layers(str(_spec(tmp_path)), str(output), str(output))
    assert output.read_bytes() == b"prior delivery"


def test_hardlinked_plan_cannot_replace_media_even_with_json_suffix(tmp_path):
    output, plan = tmp_path / "out.mp4", tmp_path / "plan.json"
    output.write_bytes(b"delivery")
    os.link(output, plan)
    with pytest.raises(MCPVideoError, match="aliases"):
        composite_layers(str(_spec(tmp_path)), str(output), str(plan), dry_run=True)
    assert output.read_bytes() == plan.read_bytes() == b"delivery"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Real FFmpeg needed")
def test_real_composite_receipt_hash_matches_published_media(tmp_path):
    output, plan = tmp_path / "out.png", tmp_path / "plan.json"
    result = composite_layers(str(_spec(tmp_path)), str(output), str(plan))
    assert output.read_bytes().startswith(b"\x89PNG")
    expected = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(plan.read_text())["output_hash"] == expected == result.layer_plan["output_hash"]
    assert result.output_path == str(output) and result.layer_plan_path == str(plan)
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Real FFmpeg needed")
def test_receipt_staging_failure_keeps_both_prior_artifacts(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    output, plan = tmp_path / "out.png", tmp_path / "plan.json"
    output.write_bytes(b"prior media")
    plan.write_bytes(b"prior plan")

    def failed_write(*args, **kwargs):
        raise OSError("artifact storage failure")

    monkeypatch.setattr("kinocut.engine_composite_layers_publication._open_staged_writer", failed_write)
    with pytest.raises(MCPVideoError):
        composite_layers(str(spec), str(output), str(plan))
    assert output.read_bytes() == b"prior media" and plan.read_bytes() == b"prior plan"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Real FFmpeg needed")
def test_postflight_failure_does_not_replace_prior_media_or_plan(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    output, plan = tmp_path / "out.mp4", tmp_path / "plan.json"
    output.write_bytes(b"prior media")
    plan.write_bytes(b"prior plan")

    def reject(*args, **kwargs):
        raise MCPVideoError("postflight failed", error_type="processing_error")

    monkeypatch.setattr("kinocut.engine_composite_layers._build_composite_result", reject)
    with pytest.raises(MCPVideoError, match="postflight failed"):
        composite_layers(str(spec), str(output), str(plan))
    assert output.read_bytes() == b"prior media" and plan.read_bytes() == b"prior plan"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
