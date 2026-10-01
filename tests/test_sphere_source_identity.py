"""Source-bound 360 replay and model fallback controls without model inference."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _reset_operation_inputs
from kinocut.te import sphere_director as director, sphere_probe, sphere_render
from tests.test_sphere_plan_adversarial import _plan


@pytest.fixture(autouse=True)
def isolated_operation():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _source_plan(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-one")
    plan = _plan()
    plan["source"].update(path=str(source), sha256="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest())
    plan["status"] = "approved"
    return source, plan


def test_stale_source_fails_before_render_or_touching_delivery(tmp_path, monkeypatch):
    source, plan = _source_plan(tmp_path)
    source.write_bytes(b"source-two")
    output = tmp_path / "delivered.mp4"
    output.write_bytes(b"prior-delivery")
    monkeypatch.setattr(
        sphere_render, "_render_window", lambda *args: pytest.fail("Unapproved replacement was rendered")
    )
    with pytest.raises(MCPVideoError) as error:
        sphere_render.render_sphere_plan(plan, str(output), allow_fail=True)
    assert error.value.code == "source_identity_changed"
    assert output.read_bytes() == b"prior-delivery"


@pytest.mark.parametrize("phase", ["render", "quality"])
def test_source_mutation_during_render_or_quality_cannot_publish_receipt(tmp_path, monkeypatch, phase):
    source, plan = _source_plan(tmp_path)
    output = tmp_path / "delivered.mp4"
    output.write_bytes(b"prior-delivery")

    def rendered(*args):
        piece = tmp_path / "piece.mp4"
        piece.write_bytes(b"rendered-video")
        if phase == "render":
            source.write_bytes(b"source-two")
        return str(piece)

    def quality(*args, **kwargs):
        if phase == "quality":
            source.write_bytes(b"source-two")
        return {"passed": True}

    monkeypatch.setattr(sphere_render, "_render_window", rendered)
    monkeypatch.setattr(sphere_render, "_maybe_quality", quality)
    with pytest.raises(MCPVideoError) as error:
        sphere_render.render_sphere_plan(plan, str(output), allow_fail=True)
    assert error.value.code == "source_identity_changed"
    assert output.read_bytes() == b"prior-delivery"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_quality_failure_preserves_delivery_and_same_source_receipt_binds_actual_hash(tmp_path, monkeypatch):
    source, plan = _source_plan(tmp_path)
    output, piece = tmp_path / "delivered.mp4", tmp_path / "piece.mp4"
    output.write_bytes(b"prior-delivery")
    piece.write_bytes(b"rendered-video")
    monkeypatch.setattr(sphere_render, "_render_window", lambda *args: str(piece))

    def rejected(*args, **kwargs):
        raise MCPVideoError("Independent quality rejection", code="quality_failed")

    monkeypatch.setattr(sphere_render, "_maybe_quality", rejected)
    with pytest.raises(MCPVideoError):
        sphere_render.render_sphere_plan(plan, str(output))
    assert output.read_bytes() == b"prior-delivery"
    monkeypatch.setattr(
        sphere_render, "_maybe_quality", lambda *args, **kwargs: {"passed": True, "report": {"video_path": args[0]}}
    )
    receipt = sphere_render.render_sphere_plan(plan, str(output))
    assert receipt["source"]["sha256"] == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    assert receipt["quality"]["report"]["video_path"] == str(output)
    assert output.read_bytes() == b"rendered-video"


def test_hash_cache_invalidates_equal_size_equal_mtime_replacement(tmp_path):
    source, replacement = tmp_path / "source.mp4", tmp_path / "replacement.mp4"
    source.write_bytes(b"equal-one")
    first = sphere_probe._file_sha256(str(source))
    before = source.stat()
    replacement.write_bytes(b"equal-two")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, source)
    assert source.stat().st_size == before.st_size and source.stat().st_mtime_ns == before.st_mtime_ns
    assert sphere_probe._file_sha256(str(source)) != first


def test_source_mutation_during_geometry_probe_is_not_combined_with_old_hash(tmp_path, monkeypatch):
    source, _ = _source_plan(tmp_path)

    def geometry(path):
        Path(path).write_bytes(b"source-two")
        return 320, 160, 10, False, ""

    monkeypatch.setattr(sphere_probe, "_probe_geometry", geometry)
    with pytest.raises(MCPVideoError) as error:
        sphere_probe.probe_360_source(str(source))
    assert error.value.code == "source_identity_changed"


def test_failed_director_mutation_does_not_corrupt_original_fallback(monkeypatch):
    original = _plan()
    original["writer"]["kind"] = "heuristic"
    expected = deepcopy(original)
    monkeypatch.setattr(director, "propose_sphere_plan", lambda *args, **kwargs: original)

    def mutating(candidate):
        candidate["source"]["path"] = "unrequested.mp4"
        candidate["output"]["width"] = float("nan")
        candidate["status"] = "approved"
        raise RuntimeError("Unavailable backend")

    fallback = director.apply_director("source.mp4", director="ollama", propose=mutating)
    assert fallback["source"] == expected["source"]
    assert fallback["output"] == expected["output"]
    assert fallback["status"] == "proposed"
    assert fallback["writer"]["unavailable"] is True


def test_valid_but_source_rebound_model_proposal_falls_back_to_requested_source(monkeypatch):
    original = _plan()
    original["writer"]["kind"] = "heuristic"
    expected = deepcopy(original)
    monkeypatch.setattr(director, "propose_sphere_plan", lambda *args, **kwargs: original)

    def rebound(candidate):
        candidate["source"]["path"] = "unrequested.mp4"
        return candidate

    fallback = director.apply_director("source.mp4", director="ollama", propose=rebound)
    assert fallback["source"] == expected["source"]
    assert fallback["status"] == "proposed" and fallback["writer"]["unavailable"] is True
