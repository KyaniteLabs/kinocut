"""Requested outputs have one caller-relative base and truthful CLI status."""

import json
from pathlib import Path

import pytest

from kinocut import hyperframes_ops as ops
from kinocut.errors import HyperframesRenderError
from kinocut.hyperframes_models import HyperframesRenderResult, HyperframesSnapshotResult


@pytest.mark.parametrize("absolute", [False, True])
def test_render_uses_same_resolved_path_for_child_and_result(tmp_path, monkeypatch, absolute):
    caller, project = tmp_path / "caller", tmp_path / "project"
    caller.mkdir()
    project.mkdir()
    monkeypatch.chdir(caller)
    requested = caller / "exports" / "clip.mp4"
    def child(operation, **kwargs):
        destination = Path(kwargs["output_path"])
        assert destination.is_absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"video")
        return None, project
    monkeypatch.setattr(ops, "_hyperframes_op", child)
    result = ops.render(str(project), output_path=str(requested) if absolute else "exports/clip.mp4")
    assert result.success
    assert result.output_path == str(requested)
    assert requested.read_bytes() == b"video"
    assert result.size_mb is not None
    assert not (project / "exports" / "clip.mp4").exists()


def test_requested_still_survives_later_snapshot_replacement(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    actual = project / "frame.png"
    monkeypatch.chdir(tmp_path)
    calls = []
    def snapshot(*args, **kwargs):
        actual.write_bytes(b"first" if not calls else b"second")
        calls.append(1)
        return HyperframesSnapshotResult(frame_paths=[str(actual)], output_dir=str(project))
    monkeypatch.setattr(ops, "snapshot", snapshot)
    first = ops.still(str(project), output_path="requested.png")
    ops.still(str(project), output_path="second.png")
    assert first.output_path == str(tmp_path / "requested.png")
    assert Path(first.output_path).read_bytes() == b"first"
    assert actual.read_bytes() == b"second"


def test_missing_still_is_explicit_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "snapshot", lambda *args, **kwargs:
                        HyperframesSnapshotResult(frame_paths=[], output_dir=str(tmp_path)))
    with pytest.raises(HyperframesRenderError, match="produced no still image"):
        ops.still(str(tmp_path), output_path=str(tmp_path / "missing.png"))


def test_missing_render_emits_json_false_and_nonzero_cli_status(tmp_path, monkeypatch, capsys):
    from kinocut.cli.handlers_hyperframes import _register_render_commands
    from kinocut.cli.parser import build_parser
    from kinocut.cli.runner import CommandRunner
    from kinocut import hyperframes_engine
    args = build_parser().parse_args(["--format", "json", "hyperframes-render", str(tmp_path),
                                     "-o", str(tmp_path / "missing.mp4")])
    monkeypatch.setattr(hyperframes_engine, "render", lambda *args, **kwargs:
                        HyperframesRenderResult(success=False, output_path=str(tmp_path / "missing.mp4")))
    runner = CommandRunner(args, True)
    _register_render_commands(runner)
    with pytest.raises(SystemExit) as failure:
        runner.dispatch()
    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out)["success"] is False
