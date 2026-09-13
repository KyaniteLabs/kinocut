"""Tests for the Revideo bridge engine (no npm/network required)."""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
from pathlib import Path

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
    install_deps,
    materialize_project,
    render,
    render_job,
)


def _fake_probe(**changes) -> dict:
    stream = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 640,
        "height": 360,
        "avg_frame_rate": "10/1",
        "nb_read_frames": "10",
    }
    format_data = {
        "duration": "1.000000",
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "tags": {"major_brand": "isom"},
    }
    for key, value in changes.items():
        (format_data if key == "duration" else stream)[key] = value
    return {"streams": [stream], "format": format_data}


_FAKE_PROBE = _fake_probe()


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
    def test_materialize_rejects_non_object_job_without_writing(self, tmp_path):
        dest = tmp_path / "bridge"
        with pytest.raises(ValidationError, match="must be an object"):
            materialize_project(dest, ["not", "an", "object"])
        assert not dest.exists()

    def test_materialize_rejects_existing_file_destination(self, tmp_path):
        dest = tmp_path / "bridge"
        dest.write_text("keep", encoding="utf-8")
        with pytest.raises(RevideoProjectError, match="not a directory"):
            materialize_project(dest, _minimal_job())
        assert dest.read_text(encoding="utf-8") == "keep"

    def test_materialize_writes_job_json(self, tmp_path):
        dest = tmp_path / "bridge"
        materialize_project(dest, _minimal_job())
        job = json.loads((dest / "src" / "job.json").read_text(encoding="utf-8"))
        assert job == {**_minimal_job(), "out_file": "video.mp4"}

    def test_materialize_accepts_empty_destination_and_ancestor_alias(self, tmp_path):
        real_parent = tmp_path / "real"
        real_parent.mkdir()
        alias_parent = tmp_path / "alias"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        dest = alias_parent / "bridge"
        dest.mkdir()
        materialize_project(dest, _minimal_job())
        assert (real_parent / "bridge" / "src" / "job.json").is_file()

    def test_materialize_rejects_destination_and_scene_leaf_symlinks(self, tmp_path):
        real_dest = tmp_path / "real-dest"
        real_dest.mkdir()
        dest_alias = tmp_path / "dest-alias"
        dest_alias.symlink_to(real_dest, target_is_directory=True)
        with pytest.raises(RevideoProjectError, match="symlink"):
            materialize_project(dest_alias, _minimal_job())

        scene = tmp_path / "scene.ts"
        scene.write_text("export default makeScene2D('art', function* () {});", encoding="utf-8")
        scene_alias = tmp_path / "scene-alias.ts"
        scene_alias.symlink_to(scene)
        with pytest.raises(RevideoProjectError, match="non-symlink"):
            materialize_project(tmp_path / "bridge", _minimal_job(), scene_source=scene_alias)

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

    def test_invalid_utf8_scene_is_typed_and_leaves_no_project(self, tmp_path):
        scene = tmp_path / "bad.ts"
        scene.write_bytes(b"\xff\xfe")
        dest = tmp_path / "bridge"
        with pytest.raises(RevideoProjectError, match="UnicodeDecodeError"):
            materialize_project(dest, _minimal_job(), scene_source=scene)
        assert not dest.exists()


class TestRender:
    @pytest.fixture(autouse=True)
    def _available_revideo_deps(self, monkeypatch):
        monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: None)

    @pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), "30"])
    def test_render_rejects_invalid_timeout_before_npm(self, tmp_path, timeout):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(ValidationError, match="timeout"):
                render(project, str(tmp_path / "out.mp4"), timeout=timeout)

    def test_render_rejects_tampered_control_file_before_npm(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        (project / "package.json").write_text("{}", encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(RevideoProjectError, match="does not match"):
                render(project, str(tmp_path / "out.mp4"))

    def test_install_rejects_tampered_control_file_before_npm(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        (project / "render.mjs").write_text("console.log('unsafe')", encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(RevideoProjectError, match="does not match"):
                install_deps(project)

    def test_render_rejects_symlinked_control_file_before_npm(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        package = project / "package.json"
        replacement = tmp_path / "package.json"
        replacement.write_bytes(package.read_bytes())
        package.unlink()
        package.symlink_to(replacement)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(RevideoProjectError, match="symlink"):
                render(project, str(tmp_path / "out.mp4"))

    def test_render_rejects_project_root_symlink_before_npm(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        alias = tmp_path / "bridge-alias"
        alias.symlink_to(project, target_is_directory=True)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(RevideoProjectError, match="root must not be a symlink"):
                render(alias, str(tmp_path / "out.mp4"))

    @pytest.mark.parametrize(
        "job_text",
        ["not-json", "[]", '{"width": "wide"}', '{"out_file": "../escape.mp4"}'],
    )
    def test_render_rejects_invalid_disk_job_before_npm(self, tmp_path, job_text):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        (project / "src" / "job.json").write_text(job_text, encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: pytest.fail("npm invoked"))
            with pytest.raises(RevideoProjectError, match="job file is invalid"):
                render(project, str(tmp_path / "out.mp4"))

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

    def test_render_success_publishes_output_and_hashes(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        out_dir = project / "out"
        commands = []

        def fake_run(*args, **kwargs):
            commands.append(args[0])
            out_dir.mkdir(exist_ok=True)
            candidate = out_dir / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]
            candidate.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            return _completed(stdout=f"\n{candidate}\n")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: _FAKE_PROBE)
            mp.setattr(
                revideo_engine,
                "_run_command",
                lambda cmd, **_kwargs: commands.append(cmd) or _completed(),
            )
            result = render(project, str(tmp_path / "delivered.mp4"))

        assert result.output_path == str(tmp_path / "delivered.mp4")
        assert (tmp_path / "delivered.mp4").is_file()
        assert len(result.output_sha256) == 64
        assert (result.width, result.height, result.fps) == (640, 360, 10.0)
        assert result.frames == 10 and result.duration_seconds == 1.0
        assert (out_dir / "video.mp4").is_file(), "verified project candidate remains available for diagnosis/retry"
        assert any(command[0].endswith("ffmpeg") and "-xerror" in command for command in commands)

    def test_render_ignores_untrusted_stdout_path(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        candidate = project / "out" / "video.mp4"
        unrelated = tmp_path / "unrelated.mp4"
        unrelated.write_bytes(b"do-not-copy")

        def fake_run(*args, **kwargs):
            candidate.parent.mkdir(exist_ok=True)
            (candidate.parent / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]).write_bytes(b"expected-project-output")
            return _completed(stdout=str(unrelated))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: _FAKE_PROBE)
            mp.setattr(revideo_engine, "_run_command", lambda *_a, **_k: _completed())
            result = render(project, str(tmp_path / "delivered.mp4"))

        assert Path(result.output_path).read_bytes() == b"expected-project-output"
        assert unrelated.read_bytes() == b"do-not-copy"

    def test_render_rejects_symlinked_output_directory(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "video.mp4").write_bytes(b"outside")
        (project / "out").symlink_to(outside, target_is_directory=True)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *_a, **_k: _completed())
            with pytest.raises(RevideoProjectError, match="symlink"):
                render(project, str(tmp_path / "delivered.mp4"))

        assert (outside / "video.mp4").read_bytes() == b"outside"
        assert not (tmp_path / "delivered.mp4").exists()

    def test_render_missing_output_raises(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", lambda *a, **k: _completed(stdout="done"))
            with pytest.raises(RevideoRenderError, match="no fresh output"):
                render(project, str(tmp_path / "out.mp4"))

    def test_render_job_requires_deps(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            revideo_engine,
            "_require_revideo_deps",
            lambda: (_ for _ in ()).throw(RevideoNotFoundError("missing")),
        )
        with pytest.raises(RevideoNotFoundError):
            render_job(_minimal_job(), str(tmp_path / "out.mp4"))

    def test_render_invalid_candidate_is_not_published(self, tmp_path):
        # Regression (CodeRabbit #473): a nonempty render candidate with no
        # video stream must be rejected BEFORE it replaces output_path.
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        output = tmp_path / "delivered" / "final.mp4"

        def fake_run(*args, **kwargs):
            candidate = project / "out" / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]
            candidate.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            return _completed()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: {"streams": [], "format": {}})
            with pytest.raises(RevideoRenderError, match="no video stream"):
                render(project, str(output))

        assert not output.exists()
        assert not list((project / "out").iterdir()), "invalid run-owned candidate is removed"

    @pytest.mark.parametrize(
        ("probe", "label"),
        [
            (_fake_probe(width="no"), "validation"),
            (_fake_probe(height=0), "validation"),
            (_fake_probe(avg_frame_rate="0/1"), "validation"),
            (_fake_probe(duration="bad"), "validation"),
        ],
    )
    def test_invalid_probe_metadata_preserves_existing_output(self, tmp_path, probe, label):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        candidate = project / "out" / "video.mp4"
        candidate.parent.mkdir()
        candidate.write_bytes(b"existing project candidate")
        output = tmp_path / "delivered.mp4"
        output.write_bytes(b"existing")

        def fake_run(*args, **kwargs):
            candidate.parent.mkdir(exist_ok=True)
            (candidate.parent / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]).write_bytes(b"candidate")
            return _completed()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: probe)
            mp.setattr(revideo_engine, "_run_command", lambda *_a, **_k: _completed())
            with pytest.raises(RevideoRenderError, match=label):
                render(project, str(output))

        assert output.read_bytes() == b"existing"
        assert candidate.read_bytes() == b"existing project candidate"
        assert not list(tmp_path.glob(".kinocut_tmp_*"))

    def test_publish_copy_failure_preserves_existing_output(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        candidate = project / "out" / "video.mp4"
        candidate.parent.mkdir()
        candidate.write_bytes(b"existing project candidate")
        output = tmp_path / "delivered.mp4"
        output.write_bytes(b"existing")

        with pytest.MonkeyPatch.context() as mp:

            def fake_run(*_args, **kwargs):
                (candidate.parent / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]).write_bytes(b"candidate")
                return _completed()

            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: _FAKE_PROBE)
            mp.setattr(revideo_engine, "_run_command", lambda *_a, **_k: _completed())
            mp.setattr(revideo_engine.shutil, "copyfile", lambda *_a, **_k: (_ for _ in ()).throw(OSError("copy")))
            with pytest.raises(RevideoRenderError, match="publication failed"):
                render(project, str(output))

        assert output.read_bytes() == b"existing"
        assert not list(tmp_path.glob(".kinocut_tmp_*"))

    def test_atomic_replace_failure_preserves_existing_output(self, tmp_path):
        project = materialize_project(tmp_path / "bridge", _minimal_job())
        candidate = project / "out" / "video.mp4"
        candidate.parent.mkdir()
        candidate.write_bytes(b"existing project candidate")
        output = tmp_path / "delivered.mp4"
        output.write_bytes(b"existing")

        with pytest.MonkeyPatch.context() as mp:

            @contextlib.contextmanager
            def fail_atomic(_path):
                raise OSError("replace")
                yield

            def fake_run(*_args, **kwargs):
                (candidate.parent / kwargs["env"][revideo_engine._RUN_OUTPUT_ENV]).write_bytes(b"candidate")
                return _completed()

            mp.setattr(revideo_engine.subprocess, "run", fake_run)
            mp.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: _FAKE_PROBE)
            mp.setattr(revideo_engine, "_run_command", lambda *_a, **_k: _completed())
            mp.setattr(revideo_engine, "_atomic_output", fail_atomic)
            with pytest.raises(RevideoRenderError, match="publication failed"):
                render(project, str(output))

        assert output.read_bytes() == b"existing"
        assert candidate.read_bytes() == b"existing project candidate"
        assert not list(tmp_path.glob(".kinocut_tmp_*"))

    @pytest.mark.parametrize("name", ["install_timeout", "render_timeout"])
    @pytest.mark.parametrize("timeout", [False, 0, -1, float("nan"), "30"])
    def test_render_job_validates_both_timeouts_before_side_effects(self, tmp_path, monkeypatch, name, timeout):
        monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
        with pytest.raises(ValidationError):
            render_job(_minimal_job(), str(tmp_path / "out.mp4"), **{name: timeout})
        assert not list(tmp_path.iterdir())


class TestRequireRevideoDepsVersion:
    @staticmethod
    def _fake_env(monkeypatch, version_stdout: str) -> None:
        monkeypatch.setattr(
            revideo_engine.shutil,
            "which",
            lambda name: "/usr/bin/node" if name in ("node", "npm") else None,
        )
        monkeypatch.setattr(
            revideo_engine.subprocess,
            "run",
            lambda *a, **k: _completed(stdout=version_stdout),
        )

    def test_rejects_node_below_floor(self, monkeypatch):
        self._fake_env(monkeypatch, "v16.14.0\n")
        with pytest.raises(RevideoNotFoundError, match=r"Node\.js 18\+"):
            revideo_engine._require_revideo_deps()

    def test_accepts_node_at_floor(self, monkeypatch):
        self._fake_env(monkeypatch, "v18.0.0\n")
        revideo_engine._require_revideo_deps()  # must not raise

    def test_accepts_modern_node(self, monkeypatch):
        self._fake_env(monkeypatch, "v22.14.0\n")
        revideo_engine._require_revideo_deps()  # must not raise

    def test_rejects_nonzero_node_probe(self, monkeypatch):
        monkeypatch.setattr(revideo_engine.shutil, "which", lambda _name: "/usr/bin/node")
        monkeypatch.setattr(
            revideo_engine.subprocess,
            "run",
            lambda *_a, **_k: _completed(stdout="v22.0.0", returncode=1),
        )
        with pytest.raises(RevideoNotFoundError, match="non-zero"):
            revideo_engine._require_revideo_deps()

    def test_rejects_unparseable_version_output(self, monkeypatch):
        self._fake_env(monkeypatch, "not-a-version\n")
        with pytest.raises(RevideoNotFoundError, match="parse"):
            revideo_engine._require_revideo_deps()
