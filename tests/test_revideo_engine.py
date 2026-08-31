"""Tests for the Revideo bridge engine (no npm/network required)."""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from kinocut import revideo_engine
from kinocut.errors import (
    RevideoNotFoundError,
    RevideoProjectError,
    RevideoRenderError,
    ValidationError,
)
from kinocut.revideo_engine import (
    TEMPLATE_DIR,
    materialize_project,
    render,
    render_job,
)

_FAKE_PROBE = {
    "streams": [{"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "10/1"}],
    "format": {"duration": "1.000000"},
}


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=["npm"], returncode=returncode, stdout=stdout, stderr=stderr)


def _minimal_job() -> dict:
    return {"width": 640, "height": 360, "fps": 10, "frames": 10, "seed": 7, "workers": 1}


class TestTemplateShips:
    def test_template_assets_are_vendored(self):
        for rel in (
            "package.json",
            "package-lock.json",
            "tsconfig.json",
            "render.mjs",
            "README.md",
            "src/project.ts",
            "src/scene.ts",
            "src/job.json",
        ):
            assert (TEMPLATE_DIR / rel).is_file(), f"missing vendored template file: {rel}"

    def test_scene_uses_named_make_scene2d(self):
        text = (TEMPLATE_DIR / "src" / "scene.ts").read_text(encoding="utf-8")
        assert "makeScene2D('bridge'" in text

    def test_lockfile_pins_exact_versions(self):
        lock = json.loads((TEMPLATE_DIR / "package-lock.json").read_text(encoding="utf-8"))
        deps = lock["packages"][""]["dependencies"]
        for name, spec in deps.items():
            assert re.fullmatch(r"\d+\.\d+\.\d+", spec), f"{name} must be pinned to an exact x.y.z version, got {spec}"


class TestMaterialize:
    def test_materialize_writes_job_json(self, tmp_path):
        dest = tmp_path / "bridge"
        materialize_project(dest, _minimal_job())
        job = json.loads((dest / "src" / "job.json").read_text(encoding="utf-8"))
        assert job == {**_minimal_job(), "out_file": "video.mp4"}

    def test_materialize_fills_defaults(self, tmp_path):
        dest = tmp_path / "bridge"
        materialize_project(dest, {"frames": 5})
        job = json.loads((dest / "src" / "job.json").read_text(encoding="utf-8"))
        assert job["width"] == 1920 and job["height"] == 1080
        assert job["fps"] == 30.0 and job["frames"] == 5

    def test_materialize_rejects_nonempty_dest(self, tmp_path):
        dest = tmp_path / "bridge"
        dest.mkdir()
        (dest / "junk.txt").write_text("x")
        with pytest.raises(RevideoProjectError):
            materialize_project(dest, _minimal_job())

    def test_materialize_rejects_out_of_bounds_job(self, tmp_path):
        with pytest.raises(ValidationError):
            materialize_project(tmp_path / "a", {"fps": 0})
        with pytest.raises(ValidationError):
            materialize_project(tmp_path / "b", {"width": 8})
        with pytest.raises(ValidationError):
            materialize_project(tmp_path / "c", {"out_file": "video.avi"})

    def test_materialize_rejects_traversal_out_file(self, tmp_path):
        # The pinned renderer writes AND unlinks along outDir/outFile paths —
        # a path separator in out_file is an arbitrary write/unlink primitive.
        for evil in ("../evil.mp4", "sub/dir/video.mp4", "..\\evil.mp4"):
            with pytest.raises(ValidationError):
                materialize_project(tmp_path / "x", {"out_file": evil})

    def test_scene_override_accepted(self, tmp_path):
        scene = tmp_path / "art.ts"
        scene.write_text(
            "import { makeScene2D } from '@revideo/2d';\nexport default makeScene2D('art', function* (view) {});\n",
            encoding="utf-8",
        )
        dest = tmp_path / "bridge"
        materialize_project(dest, _minimal_job(), scene_source=scene)
        assert "makeScene2D('art'" in (dest / "src" / "scene.ts").read_text(encoding="utf-8")

    def test_scene_override_missing_name_rejected(self, tmp_path):
        scene = tmp_path / "broken.ts"
        scene.write_text(
            "import { makeScene2D } from '@revideo/2d';\nexport default makeScene2D(function* (view) {});\n",
            encoding="utf-8",
        )
        with pytest.raises(RevideoProjectError, match="FIRST argument"):
            materialize_project(tmp_path / "bridge", _minimal_job(), scene_source=scene)

    def test_scene_override_missing_file_rejected(self, tmp_path):
        with pytest.raises(RevideoProjectError):
            materialize_project(tmp_path / "bridge", _minimal_job(), scene_source=tmp_path / "nope.ts")


class TestRender:
    def test_render_requires_materialized_project(self, tmp_path):
        with pytest.raises(RevideoProjectError):
            render(tmp_path, str(tmp_path / "out.mp4"))

    def test_render_timeout_raises(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())

        def explode(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="npm", timeout=1)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", explode)
            with pytest.raises(RevideoRenderError, match="timed out"):
                render(project, str(tmp_path / "out.mp4"))

    def test_render_nonzero_exit_raises(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                revideo_engine.subprocess,
                "run",
                lambda *a, **k: _completed(stderr="boom", returncode=2),
            )
            with pytest.raises(RevideoRenderError, match="boom"):
                render(project, str(tmp_path / "out.mp4"))

    def test_render_success_moves_output_and_hashes(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        out_dir = project / "out"

        def fake_run(*args, **kwargs):
            out_dir.mkdir(exist_ok=True)
            (out_dir / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
            return _completed(stdout=f"\n{out_dir / 'video.mp4'}\n")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: _FAKE_PROBE)
            result = render(project, str(tmp_path / "delivered.mp4"))

        assert result.output_path == str(tmp_path / "delivered.mp4")
        assert (tmp_path / "delivered.mp4").is_file()
        assert len(result.output_sha256) == 64
        assert (result.width, result.height, result.fps) == (640, 360, 10.0)
        assert result.frames == 10 and result.duration_seconds == 1.0

    def test_render_missing_output_raises(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *a, **k: _completed(stdout="done"))
            with pytest.raises(RevideoRenderError, match="no output file"):
                render(project, str(tmp_path / "out.mp4"))

    def test_render_job_requires_deps(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            revideo_engine.shutil,
            "which",
            lambda name: None if name in ("node", "npm") else "/usr/bin/x",
        )
        with pytest.raises(RevideoNotFoundError):
            render_job(_minimal_job(), str(tmp_path / "out.mp4"))
