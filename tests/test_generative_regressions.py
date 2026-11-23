"""Regressions for the generative surface (roast audit D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-12, D-18).

Hyperframes overwrote a non-empty project directory after printing a warning to
stdout (which also corrupts the MCP stdio stream), fell back to stale snapshot
frames when it wrote none, defaulted render output to ``./out`` in the server's
working directory, raised on a failing ``doctor`` before the result could be
reported, and ignored ``render_and_post``'s ``output_path``. Stem separation
returned a partial dict as success, and object-matte decoded autorotated frames
into unrotated dimensions.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import kinocut.hyperframes_ops as ops
import kinocut.hyperframes_ops_helpers as helpers
from kinocut.ai_engine.stem import _run_demucs_separation
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.hyperframes_engine import HyperframesRenderError
from kinocut.object_matte.media import decode_video_argv

# --- D-06 / D-07: create_project must not overwrite -------------------------------


def test_create_project_refuses_a_non_empty_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ops, "_require_hyperframes_deps", lambda **kwargs: None)
    ran = []
    monkeypatch.setattr(ops, "_hyperframes_op", lambda *args, **kwargs: ran.append(args))
    (tmp_path / "existing").mkdir()
    (tmp_path / "existing" / "composition.html").write_text("<html>user work</html>")

    with pytest.raises(MCPVideoError) as refused:
        ops.create_project("existing", output_dir=str(tmp_path))
    assert refused.value.code == "output_exists"
    assert not ran
    assert (tmp_path / "existing" / "composition.html").read_text() == "<html>user work</html>"
    assert capsys.readouterr().out == ""


# --- D-04: snapshots are only what this call wrote --------------------------------


def _patch_snapshot_plumbing(monkeypatch, project: Path, writer):
    monkeypatch.setattr(ops, "_require_node", lambda: None)
    monkeypatch.setattr(ops, "_validate_project", lambda _path: (project, project / "index.html"))

    def fake_op(*args, **kwargs):
        writer()
        return SimpleNamespace(returncode=0, stdout="", stderr=""), project

    monkeypatch.setattr(ops, "_hyperframes_op", fake_op)


def test_snapshot_never_passes_stale_frames_off_as_new(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "snapshots").mkdir(parents=True)
    (project / "snapshots" / "old.png").write_bytes(b"stale")
    _patch_snapshot_plumbing(monkeypatch, project, lambda: None)

    with pytest.raises(HyperframesRenderError, match="no new snapshot frames"):
        ops.snapshot(str(project))


def test_snapshot_returns_only_the_frames_it_wrote(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "snapshots").mkdir(parents=True)
    (project / "snapshots" / "old.png").write_bytes(b"stale")

    def write_new():
        (project / "snapshots" / "new.png").write_bytes(b"fresh")

    _patch_snapshot_plumbing(monkeypatch, project, write_new)

    result = ops.snapshot(str(project))
    assert [Path(path).name for path in result.frame_paths] == ["new.png"]


def test_snapshot_pngs_helper_has_no_fallback(tmp_path):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "a.png").write_bytes(b"a")
    assert helpers._snapshot_pngs(tmp_path, set()) == [str(snapshot_dir / "a.png")]
    assert helpers._snapshot_pngs(tmp_path, {snapshot_dir / "a.png"}) == []


# --- D-09: default render output is namespaced by project ------------------------


def test_default_render_output_lives_inside_the_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "deep" / "proj"
    project.mkdir(parents=True)
    default = helpers._default_render_output(str(project), "mp4")
    assert default == str(project / "renders" / "proj.mp4")
    assert not (tmp_path / "out").exists()
    other = tmp_path / "elsewhere" / "proj"
    other.mkdir(parents=True)
    assert helpers._default_render_output(str(other), "mp4") != default


# --- D-10: doctor reports instead of raising --------------------------------------


def test_doctor_reports_a_failing_environment(tmp_path, monkeypatch):
    import kinocut.hyperframes_engine as engine

    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kwargs: None)
    monkeypatch.setattr(
        engine,
        "_run_hyperframes",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout='{"node":"missing"}', stderr=""),
    )
    monkeypatch.setattr(ops, "_require_node", lambda: None)

    result = ops.doctor()
    assert result.data == {"node": "missing"}


# --- D-18: render_and_post honours output_path ------------------------------------


def test_render_and_post_passes_output_path_to_render(tmp_path, monkeypatch):
    seen = {}

    def fake_render(project_path, output_path=None, **kwargs):
        seen["output_path"] = output_path
        return SimpleNamespace(success=True, output_path=output_path or str(tmp_path / "default.mp4"))

    monkeypatch.setattr(ops, "render", fake_render)
    target = str(tmp_path / "requested.mp4")
    result = ops.render_and_post(str(tmp_path / "proj"), [], output_path=target)
    assert seen["output_path"] == target
    assert result.hyperframes_output == target
    assert result.final_output == target


# --- D-05: nothing on an MCP path writes to stdout --------------------------------


def _stdout_print_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]


@pytest.mark.parametrize(
    "relative",
    [
        "ai_engine/upscale.py",
        "hyperframes_ops.py",
        "hyperframes_engine.py",
        "server_tools_hyperframes.py",
        "server_app.py",
    ],
)
def test_mcp_reachable_modules_never_print_to_stdout(relative):
    package = Path(ops.__file__).parent
    assert _stdout_print_calls(package / relative) == []


# --- D-08: object matte decodes coded frames, not autorotated ones -----------------


def test_decode_argv_disables_autorotation():
    argv = decode_video_argv("clip.mp4", 1080, 1920)
    assert "-noautorotate" in argv
    assert argv.index("-noautorotate") < argv.index("-i")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_rotated_footage_decodes_to_the_probed_coded_dimensions(tmp_path):
    plain, rotated = tmp_path / "plain.mp4", tmp_path / "rotated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=64x32:r=5:d=1",
            "-pix_fmt",
            "yuv420p",
            str(plain),
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "90", "-i", str(plain), "-c", "copy", str(rotated)],
        check=True,
        timeout=120,
    )

    def first_frame(path):
        raw = subprocess.run(decode_video_argv(str(path), 64, 32), check=True, capture_output=True, timeout=120).stdout
        return raw[: 64 * 32 * 3]

    assert first_frame(rotated) == first_frame(plain)


# --- D-12: every requested stem must exist ----------------------------------------


def test_stem_separation_fails_when_a_requested_stem_is_missing(tmp_path, monkeypatch):
    import kinocut.ai_engine.stem as stem_module

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    output = tmp_path / "demucs"

    def partial_demucs(cmd, **kwargs):
        stem_dir = output / "htdemucs" / "song"
        stem_dir.mkdir(parents=True)
        (stem_dir / "vocals.wav").write_bytes(b"RIFF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(stem_module.subprocess, "run", partial_demucs)

    with pytest.raises(ProcessingError, match="drums"):
        _run_demucs_separation(str(audio), output, "htdemucs", ["vocals", "drums"])
