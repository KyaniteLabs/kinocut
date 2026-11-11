"""Ownership survives a worker restart without adopting foreign JSON files."""

import os
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_write_path
from kinocut.output_policy import output_operation
from kinocut.projectstore.receipt_ownership import durable_receipt_ownership
from kinocut.workflow.receipt import _write_receipt


def test_durable_receipt_is_owned_after_restart(tmp_path):
    target = tmp_path / "receipt.json"
    with output_operation(), durable_receipt_ownership(target):
        _write_receipt({"status": "in_progress"}, str(target), tmp_path, overwrite=True)
    with output_operation(), durable_receipt_ownership(target):
        _write_receipt({"status": "completed"}, str(target), tmp_path, overwrite=True)
    assert '"completed"' in target.read_text()


@pytest.mark.parametrize("replace_owned", [False, True])
def test_foreign_receipt_cannot_be_adopted(tmp_path, replace_owned):
    target = tmp_path / "receipt.json"
    if replace_owned:
        with output_operation(), durable_receipt_ownership(target):
            _write_receipt({"status": "in_progress"}, str(target), tmp_path, overwrite=True)
    foreign = tmp_path / "foreign.json"
    foreign.write_text('{"status":"completed"}')
    os.replace(foreign, target)
    before = target.read_bytes()
    with output_operation(True), pytest.raises(MCPVideoError), durable_receipt_ownership(target):
        pytest.fail("A foreign inode must not acquire job ownership")
    assert target.read_bytes() == before


def test_caller_suffix_allowlist_cannot_admit_foreign_nonmedia(tmp_path):
    target = tmp_path / "model.onnx"
    target.write_bytes(b"foreign model")
    with output_operation(True), pytest.raises(MCPVideoError):
        _validate_write_path(str(target), allowed_existing_suffixes=frozenset({".onnx"}), label="Model")
    assert target.read_bytes() == b"foreign model"


@pytest.mark.parametrize("variable", ["HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"])
@pytest.mark.parametrize("overwrite", [False, True])
def test_configured_agent_home_is_protected(tmp_path, monkeypatch, variable, overwrite):
    from kinocut.ffmpeg_helpers import _validate_output_path

    config_home = tmp_path / "custom-profile"
    monkeypatch.setenv(variable, str(config_home))
    with output_operation(overwrite), pytest.raises(MCPVideoError):
        _validate_output_path(str(config_home / "output.mp4"))
    assert not config_home.exists()


def test_release_receipt_failure_preserves_foreign_file(tmp_path, monkeypatch):
    from kinocut.projectstore import repurpose_policy

    target = tmp_path / "receipt.json"
    target.write_text("foreign")
    monkeypatch.setattr(repurpose_policy, "job_receipt_path", lambda *_: target)
    with output_operation(True), pytest.raises(MCPVideoError):
        repurpose_policy._persist_release_receipt(SimpleNamespace(root=tmp_path), "job", {})
    assert target.read_text() == "foreign"


def test_hls_preserves_existing_nonmedia_and_agent_home(tmp_path, monkeypatch):
    from kinocut.engine_hls import _prepare_hls_directory

    output = tmp_path / "hls"
    output.mkdir()
    target = output / "session.json"
    target.write_text("foreign")
    with output_operation(True), pytest.raises(MCPVideoError):
        _prepare_hls_directory("input.mp4", str(output), "session.json")
    assert target.read_text() == "foreign"
    monkeypatch.setenv("HOME", str(tmp_path))
    sensitive = tmp_path / ".hermes" / "output"
    with output_operation(True), pytest.raises(MCPVideoError):
        _prepare_hls_directory("input.mp4", str(sensitive), "playlist.m3u8")
    assert not sensitive.exists()


def _scratch_inside(tmp_path, monkeypatch, variable, scratch_rel):
    import tempfile

    config_home = tmp_path / "custom-profile"
    scratch = config_home / scratch_rel if scratch_rel else config_home
    scratch.mkdir(parents=True)
    monkeypatch.setenv(variable, str(config_home))
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return config_home, scratch


@pytest.mark.parametrize("variable", ["HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"])
def test_temp_dir_inside_agent_home_is_writable(tmp_path, monkeypatch, variable):
    from kinocut.ffmpeg_helpers import _validate_output_path

    config_home, scratch = _scratch_inside(tmp_path, monkeypatch, variable, "cache/scratch")
    work = scratch / "kinocut-shorts-x"
    work.mkdir()
    with output_operation():
        _validate_output_path(str(work / "seg0.mp4"))
    with output_operation(), pytest.raises(MCPVideoError):
        _validate_output_path(str(config_home / "output.mp4"))


def test_temp_dir_equal_to_agent_home_stays_protected(tmp_path, monkeypatch):
    from kinocut.ffmpeg_helpers import _validate_output_path

    config_home, _ = _scratch_inside(tmp_path, monkeypatch, "HERMES_HOME", "")
    with output_operation(), pytest.raises(MCPVideoError):
        _validate_output_path(str(config_home / "output.mp4"))


def test_video_shorts_runs_with_tmpdir_inside_hermes_home(sample_video, tmp_path, monkeypatch):
    from kinocut.product import shorts_flow

    _scratch_inside(tmp_path, monkeypatch, "HERMES_HOME", "cache/scratch")
    output = tmp_path / "out" / "short.mp4"
    output.parent.mkdir()
    result = shorts_flow.video_shorts(
        sample_video,
        [{"start": 0, "end": 1}, {"start": 1, "end": 2}],
        output_path=str(output),
    )
    assert result["success"]
    assert output.exists()
