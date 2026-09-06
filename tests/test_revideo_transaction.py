"""Fresh-output and rollback contracts for the Revideo bridge."""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kinocut import revideo_engine
from kinocut.errors import RevideoNotFoundError, RevideoProjectError, RevideoRenderError, ValidationError
from kinocut.revideo_engine import install_deps, materialize_project, render, render_job


def _job() -> dict:
    return {"width": 640, "height": 360, "fps": 10, "frames": 10, "seed": 7, "workers": 1}


def _probe(**changes) -> dict:
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


def _completed(returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["npm"], returncode, "ignored stdout", stderr)


def _render_fake(project: Path, payload: bytes = b"fresh-render"):
    def fake(*args, **kwargs):
        output_name = kwargs["extra_env"][revideo_engine._RUN_OUTPUT_ENV]
        (project / "out" / output_name).write_bytes(payload)
        return _completed()

    return fake


def _mock_media(monkeypatch, probe: dict | None = None) -> None:
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: None)
    monkeypatch.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: probe or _probe())
    monkeypatch.setattr(revideo_engine, "_run_command", lambda *a, **k: _completed())


def test_template_accepts_only_engine_output_override() -> None:
    text = (revideo_engine.TEMPLATE_DIR / "render.mjs").read_text(encoding="utf-8")
    assert "process.env.KINOCUT_REVIDEO_OUTPUT_FILE" in text
    assert "outDir: 'out'" in text
    assert "job.out_file" in text


@pytest.mark.parametrize("kind", ["out", "canonical"])
def test_owned_output_symlinks_are_rejected_before_dependency_probe_or_npm(tmp_path, monkeypatch, kind) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind == "out":
        (project / "out").symlink_to(outside, target_is_directory=True)
    else:
        (project / "out").mkdir()
        target = outside / "target.mp4"
        target.write_bytes(b"keep")
        (project / "out" / "video.mp4").symlink_to(target)
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: pytest.fail("npm invoked"))

    with pytest.raises(RevideoProjectError, match="symlink"):
        render(project, str(tmp_path / "final.mp4"))

    assert not (tmp_path / "final.mp4").exists()


@pytest.mark.parametrize("kind", ["out-file", "canonical-directory"])
def test_owned_output_unexpected_types_are_rejected_before_npm(tmp_path, monkeypatch, kind) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    if kind == "out-file":
        (project / "out").write_bytes(b"wrong type")
    else:
        (project / "out" / "video.mp4").mkdir(parents=True)
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: pytest.fail("npm invoked"))

    with pytest.raises(RevideoProjectError, match="must be a"):
        render(project, str(tmp_path / "final.mp4"))


def test_success_without_private_output_never_publishes_stale_canonical(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"stale")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: _completed())

    with pytest.raises(RevideoRenderError, match="no fresh output"):
        render(project, str(final))

    assert canonical.read_bytes() == b"stale"
    assert final.read_bytes() == b"old-final"


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        (_probe(width=320), "width"),
        (_probe(height=240), "height"),
        (_probe(avg_frame_rate="5/1"), "frame rate"),
        (_probe(nb_read_frames="9"), "frame count"),
        (_probe(duration="9"), "duration"),
    ],
)
def test_media_mismatch_preserves_project_and_external_outputs(tmp_path, monkeypatch, probe, message) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch, probe)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    with pytest.raises(RevideoRenderError, match=message):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"
    assert sorted(path.name for path in (project / "out").iterdir()) == ["video.mp4"]


def test_job_mutation_after_npm_preserves_outputs(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)

    def mutate(*args, **kwargs):
        _render_fake(project)(*args, **kwargs)
        changed = {**_job(), "frames": 9, "out_file": "video.mp4"}
        (project / "src" / "job.json").write_text(json.dumps(changed), encoding="utf-8")
        return _completed()

    monkeypatch.setattr(revideo_engine, "_run_npm", mutate)
    with pytest.raises(RevideoProjectError, match="changed during render"):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"


def test_external_publication_failure_restores_project_output(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    @contextlib.contextmanager
    def fail_publish(_path):
        yield str(tmp_path / ".external-stage.mp4")
        raise OSError("publish")

    monkeypatch.setattr(revideo_engine, "_atomic_output", fail_publish)
    with pytest.raises(RevideoRenderError, match="publication failed"):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"
    assert sorted(path.name for path in (project / "out").iterdir()) == ["video.mp4"]


def test_external_publication_failure_restores_absent_project_output(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    @contextlib.contextmanager
    def fail_publish(_path):
        yield str(tmp_path / ".external-stage.mp4")
        raise OSError("publish")

    monkeypatch.setattr(revideo_engine, "_atomic_output", fail_publish)
    with pytest.raises(RevideoRenderError, match="publication failed"):
        render(project, str(final))

    assert final.read_bytes() == b"old-final"
    assert not (project / "out" / "video.mp4").exists()
    assert not list((project / "out").iterdir())


def test_npm_failure_preserves_both_outputs_and_cleans_run_leaf(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)

    def fail(*args, **kwargs):
        _render_fake(project)(*args, **kwargs)
        return _completed(2, "renderer failed")

    monkeypatch.setattr(revideo_engine, "_run_npm", fail)
    with pytest.raises(RevideoRenderError, match="renderer failed"):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"
    assert sorted(path.name for path in (project / "out").iterdir()) == ["video.mp4"]


@pytest.mark.parametrize("copy_number", [1, 2])
def test_copy_tampering_is_rejected_and_both_outputs_are_restored(tmp_path, monkeypatch, copy_number) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))
    real_copyfile = revideo_engine.shutil.copyfile
    copies = []

    def corrupt_copy(source, destination, *args, **kwargs):
        result = real_copyfile(source, destination, *args, **kwargs)
        copies.append(Path(destination))
        if len(copies) == copy_number:
            Path(destination).write_bytes(b"corrupt-copy")
        return result

    monkeypatch.setattr(revideo_engine.shutil, "copyfile", corrupt_copy)
    with pytest.raises(RevideoRenderError, match="SHA-256 verification"):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"
    assert sorted(path.name for path in (project / "out").iterdir()) == ["video.mp4"]


def test_success_replaces_both_outputs_and_returns_observed_receipt(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    result = render(project, str(final))

    assert canonical.read_bytes() == b"fresh-render"
    assert final.read_bytes() == b"fresh-render"
    assert (result.width, result.height, result.fps, result.frames, result.duration_seconds) == (
        640,
        360,
        10.0,
        10,
        1.0,
    )
    assert len(result.output_sha256) == len(result.job_sha256) == 64
    assert sorted(path.name for path in (project / "out").iterdir()) == ["video.mp4"]


def test_private_render_keeps_job_scene_and_cwd_stable(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    job_bytes = (project / "src" / "job.json").read_bytes()
    scene_bytes = (project / "src" / "scene.ts").read_bytes()
    observed = {}
    _mock_media(monkeypatch)

    def fake(*args, **kwargs):
        observed["cwd"] = args[1]
        observed["name"] = kwargs["extra_env"][revideo_engine._RUN_OUTPUT_ENV]
        (project / "out" / observed["name"]).write_bytes(b"fresh-render")
        return _completed()

    monkeypatch.setattr(revideo_engine, "_run_npm", fake)
    render(project, str(tmp_path / "final.mp4"))

    assert observed["cwd"] == project
    assert Path(observed["name"]).name == observed["name"]
    assert observed["name"].endswith(".mp4")
    assert (project / "src" / "job.json").read_bytes() == job_bytes
    assert (project / "src" / "scene.ts").read_bytes() == scene_bytes


def test_job_digest_binds_exact_complete_file_bytes(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    job_path = project / "src" / "job.json"
    raw = b'{"width":640,"height":360,"fps":10,"frames":10,"workers":1,"seed":7,"out_file":"video.mp4","palette":"warm"}\n'
    job_path.write_bytes(raw)
    _mock_media(monkeypatch)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    result = render(project, str(tmp_path / "final.mp4"))

    assert result.job_sha256 == hashlib.sha256(raw).hexdigest()


def test_materialize_preserves_custom_job_fields(tmp_path) -> None:
    custom = {**_job(), "palette": ["#fff", "#000"], "puppeteer": {"executablePath": "/trusted/browser"}}
    project = materialize_project(tmp_path / "bridge", custom)

    assert json.loads((project / "src" / "job.json").read_text(encoding="utf-8")) == {
        **custom,
        "out_file": "video.mp4",
    }


def test_materialized_job_read_is_bounded(tmp_path, monkeypatch) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    (project / "src" / "job.json").write_bytes(b" " * (revideo_engine.MAX_REVIDEO_JOB_JSON_BYTES + 1))
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))

    with pytest.raises(RevideoProjectError, match="1 MiB"):
        render(project, str(tmp_path / "final.mp4"))


@pytest.mark.parametrize(
    ("field", "value"),
    [("puppeteer", {"executablePath": "/trusted/browser"}), ("palette", "warm")],
)
def test_renderer_visible_custom_job_mutation_preserves_outputs(tmp_path, monkeypatch, field, value) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    job_path = project / "src" / "job.json"
    raw = json.loads(job_path.read_text(encoding="utf-8"))
    raw[field] = value
    job_path.write_text(json.dumps(raw), encoding="utf-8")
    (project / "out").mkdir()
    canonical = project / "out" / "video.mp4"
    canonical.write_bytes(b"old-project")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch)

    def mutate(*args, **kwargs):
        _render_fake(project)(*args, **kwargs)
        changed = json.loads(job_path.read_text(encoding="utf-8"))
        changed[field] = {"changed": True} if isinstance(value, dict) else "cool"
        job_path.write_text(json.dumps(changed), encoding="utf-8")
        return _completed()

    monkeypatch.setattr(revideo_engine, "_run_npm", mutate)
    with pytest.raises(RevideoProjectError, match="changed during render"):
        render(project, str(final))

    assert canonical.read_bytes() == b"old-project"
    assert final.read_bytes() == b"old-final"


_SUFFIX_MISMATCHES = [
    (left, right) for left in ("mp4", "webm", "mov") for right in ("mp4", "webm", "mov") if left != right
]


@pytest.mark.parametrize(("job_suffix", "output_suffix"), _SUFFIX_MISMATCHES)
def test_staged_render_rejects_suffix_mismatch_before_dependencies(
    tmp_path, monkeypatch, job_suffix, output_suffix
) -> None:
    project = materialize_project(tmp_path / "bridge", {**_job(), "out_file": f"video.{job_suffix}"})
    output = tmp_path / f"final.{output_suffix}"
    output.write_bytes(b"old-final")
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: pytest.fail("npm invoked"))

    with pytest.raises(ValidationError, match="suffix"):
        render(project, str(output))

    assert output.read_bytes() == b"old-final"


@pytest.mark.parametrize(("job_suffix", "output_suffix"), _SUFFIX_MISMATCHES)
def test_one_shot_rejects_suffix_mismatch_before_dependencies(tmp_path, monkeypatch, job_suffix, output_suffix) -> None:
    output = tmp_path / f"final.{output_suffix}"
    output.write_bytes(b"old-final")
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    monkeypatch.setattr(revideo_engine, "_install_validated", lambda *a, **k: pytest.fail("install invoked"))
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: pytest.fail("npm invoked"))

    with pytest.raises(ValidationError, match="suffix"):
        render_job({**_job(), "out_file": f"video.{job_suffix}"}, str(output), work_dir=tmp_path / "work")

    assert output.read_bytes() == b"old-final"
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_unverified_private_output_type_is_rejected_and_cleaned(tmp_path, monkeypatch, kind) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    _mock_media(monkeypatch)

    def fake(*_args, **kwargs):
        candidate = project / "out" / kwargs["extra_env"][revideo_engine._RUN_OUTPUT_ENV]
        if kind == "symlink":
            candidate.symlink_to(outside)
        else:
            candidate.mkdir()
        return _completed()

    monkeypatch.setattr(revideo_engine, "_run_npm", fake)
    with pytest.raises(RevideoRenderError, match="no fresh output"):
        render(project, str(tmp_path / "final.mp4"))

    assert outside.read_bytes() == b"outside"
    assert not list((project / "out").iterdir())


@pytest.mark.parametrize(
    "probe",
    [
        _probe(width=10**400),
        _probe(height=10**400),
        _probe(nb_read_frames=10**400),
        _probe(avg_frame_rate=f"{10**400}/1"),
        _probe(avg_frame_rate=f"1/{10**400}"),
        _probe(duration=10**400),
    ],
)
def test_huge_probe_numbers_are_typed_and_preserve_outputs(tmp_path, monkeypatch, probe) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")
    _mock_media(monkeypatch, probe)
    monkeypatch.setattr(revideo_engine, "_run_npm", _render_fake(project))

    with pytest.raises(RevideoRenderError, match="validation failed"):
        render(project, str(final))

    assert final.read_bytes() == b"old-final"
    assert not (project / "out" / "video.mp4").exists()


def test_huge_public_numbers_are_typed_before_side_effects(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    with pytest.raises(ValidationError):
        render_job({**_job(), "fps": 10**400}, str(tmp_path / "a.mp4"))
    project = materialize_project(tmp_path / "bridge", _job())
    with pytest.raises(ValidationError):
        render(project, str(tmp_path / "b.mp4"), timeout=10**400)
    assert not (tmp_path / "a.mp4").exists()
    assert not (tmp_path / "b.mp4").exists()


@pytest.mark.parametrize("name", ["install_timeout", "render_timeout"])
def test_huge_render_job_timeouts_are_typed_before_side_effects(tmp_path, monkeypatch, name) -> None:
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    with pytest.raises(ValidationError):
        render_job(_job(), str(tmp_path / "out.mp4"), work_dir=tmp_path / "work", **{name: 10**400})
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("entry", ["install", "render", "job"])
def test_each_npm_entrypoint_enforces_dependency_floor_before_npm(tmp_path, monkeypatch, entry) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    calls = []

    def reject():
        calls.append("probe")
        raise RevideoNotFoundError("old Node")

    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", reject)
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: pytest.fail("npm invoked"))
    with pytest.raises(RevideoNotFoundError):
        if entry == "install":
            install_deps(project)
        elif entry == "render":
            render(project, str(tmp_path / "out.mp4"))
        else:
            render_job(_job(), str(tmp_path / "out.mp4"), work_dir=tmp_path / "work")
    assert calls == ["probe"]


@pytest.mark.parametrize("entry", ["install", "render", "job"])
@pytest.mark.parametrize("mode", ["missing", "old"])
def test_each_entrypoint_rejects_missing_or_old_node_without_npm(tmp_path, monkeypatch, entry, mode) -> None:
    project = materialize_project(tmp_path / "bridge", _job())
    node = str(tmp_path / "node")
    npm = str(tmp_path / "npm")
    monkeypatch.setattr(
        revideo_engine.shutil,
        "which",
        lambda name: None if mode == "missing" and name == "node" else {"node": node, "npm": npm}.get(name),
    )

    def probe_only(command, **_kwargs):
        assert command == [node, "--version"], "npm was invoked"
        return subprocess.CompletedProcess(command, 0, "v16.20.0\n", "")

    monkeypatch.setattr(revideo_engine.subprocess, "run", probe_only)
    with pytest.raises(RevideoNotFoundError):
        if entry == "install":
            install_deps(project)
        elif entry == "render":
            render(project, str(tmp_path / "out.mp4"))
        else:
            render_job(_job(), str(tmp_path / "out.mp4"), work_dir=tmp_path / "work")


def test_render_job_probes_dependencies_once(tmp_path, monkeypatch) -> None:
    calls = []

    def probe_deps():
        calls.append("probe")

    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", probe_deps)
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *a, **k: _completed())
    monkeypatch.setattr(revideo_engine, "_render_validated", lambda *a, **k: "receipt")
    assert render_job(_job(), str(tmp_path / "out.mp4"), work_dir=tmp_path / "work") == "receipt"
    assert calls == ["probe"]
