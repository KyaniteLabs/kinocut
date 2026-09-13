"""Closed Revideo exporter selection and encoded-media identity contracts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut import revideo_engine
from kinocut.errors import RevideoProjectError, RevideoRenderError, ValidationError
from kinocut.revideo_engine import materialize_project, render, render_job

_FORMATS = {
    "mp4": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "codec_name": "h264", "major_brand": "isom"},
    "webm": {"format_name": "matroska,webm", "codec_name": "vp9"},
    "mov": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "codec_name": "prores",
        "major_brand": "qt  ",
        "profile": "4444",
    },
}
_IDENTITY_FIELDS = [
    *((suffix, "format_name") for suffix in _FORMATS),
    *((suffix, "codec_name") for suffix in _FORMATS),
    ("mp4", "major_brand"),
    ("mov", "major_brand"),
    ("mov", "profile"),
]


def _job(suffix: str) -> dict:
    return {
        "width": 640,
        "height": 360,
        "fps": 10,
        "frames": 10,
        "seed": 7,
        "workers": 1,
        "out_file": f"video.{suffix}",
    }


def _probe(suffix: str) -> dict:
    identity = _FORMATS[suffix]
    stream = {
        "codec_type": "video",
        "codec_name": identity["codec_name"],
        "width": 640,
        "height": 360,
        "avg_frame_rate": "10/1",
        "nb_read_frames": "10",
    }
    if "profile" in identity:
        stream["profile"] = identity["profile"]
    format_data = {"duration": "1.000000", "format_name": identity["format_name"]}
    if "major_brand" in identity:
        format_data["tags"] = {"major_brand": identity["major_brand"]}
    return {"streams": [stream], "format": format_data}


def _bad_probe(suffix: str, field: str, mode: str) -> dict:
    probe = _probe(suffix)
    owner = probe["format"] if field == "format_name" else probe["streams"][0]
    key = field
    if field == "major_brand":
        owner = probe["format"].setdefault("tags", {})
        key = "major_brand"
    if mode == "missing":
        owner.pop(key, None)
    elif mode == "non-string":
        owner[key] = 7
    else:
        owner[key] = {"format_name": "avi", "codec_name": "av1", "major_brand": "mp42", "profile": "422"}[field]
    return probe


def _completed() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["npm"], 0, "", "")


def _mock_pipeline(monkeypatch, probe: dict, calls: list[tuple[Path, str]]) -> None:
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: None)
    monkeypatch.setattr(revideo_engine, "_install_validated", lambda *_a, **_k: None)
    monkeypatch.setattr(revideo_engine, "_run_ffprobe_json", lambda *_a, **_k: probe)
    monkeypatch.setattr(revideo_engine, "_run_command", lambda *_a, **_k: _completed())

    def fake_npm(_args, cwd, _timeout, *, extra_env=None):
        output_name = extra_env[revideo_engine._RUN_OUTPUT_ENV]
        calls.append((cwd, output_name))
        (cwd / "out" / output_name).write_bytes(b"fresh-render")
        return _completed()

    monkeypatch.setattr(revideo_engine, "_run_npm", fake_npm)


@pytest.mark.parametrize("entry", ["staged", "one-shot"])
@pytest.mark.parametrize("suffix", ["mp4", "webm", "mov"])
def test_case_equivalent_destination_keeps_private_suffix_and_publishes(tmp_path, monkeypatch, entry, suffix) -> None:
    calls: list[tuple[Path, str]] = []
    _mock_pipeline(monkeypatch, _probe(suffix), calls)
    output = tmp_path / f"final.{suffix.upper()}"
    if entry == "staged":
        project = materialize_project(tmp_path / "bridge", _job(suffix))
        result = render(project, str(output))
    else:
        project = tmp_path / "work" / "bridge"
        result = render_job(_job(suffix), str(output), work_dir=tmp_path / "work")

    assert result.output_path == str(output)
    assert output.read_bytes() == b"fresh-render"
    assert len(calls) == 1
    assert calls[0][0] == project
    assert calls[0][1].endswith(f".{suffix}")
    assert (project / "out" / f"video.{suffix}").read_bytes() == b"fresh-render"


@pytest.mark.parametrize(("suffix", "codec_name"), [("mp4", "mpeg4"), ("webm", "vp8")])
def test_closed_alternate_codec_rows_are_accepted(tmp_path, monkeypatch, suffix, codec_name) -> None:
    probe = _probe(suffix)
    probe["streams"][0]["codec_name"] = codec_name
    calls: list[tuple[Path, str]] = []
    _mock_pipeline(monkeypatch, probe, calls)

    result = render_job(_job(suffix), str(tmp_path / f"final.{suffix}"), work_dir=tmp_path / "work")

    assert result.output_sha256
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["wrong", "missing", "non-string"])
@pytest.mark.parametrize(("suffix", "field"), _IDENTITY_FIELDS)
def test_media_identity_failure_preserves_outputs(tmp_path, monkeypatch, suffix, field, mode) -> None:
    project = materialize_project(tmp_path / "bridge", _job(suffix))
    (project / "out").mkdir()
    canonical = project / "out" / f"video.{suffix}"
    canonical.write_bytes(b"old-project")
    output = tmp_path / f"final.{suffix}"
    output.write_bytes(b"old-final")
    calls: list[tuple[Path, str]] = []
    _mock_pipeline(monkeypatch, _bad_probe(suffix, field, mode), calls)

    with pytest.raises(RevideoRenderError, match="render output"):
        render(project, str(output))

    assert len(calls) == 1
    assert canonical.read_bytes() == b"old-project"
    assert output.read_bytes() == b"old-final"
    assert sorted(path.name for path in (project / "out").iterdir()) == [f"video.{suffix}"]


@pytest.mark.parametrize("entry", ["staged", "one-shot"])
def test_uppercase_job_suffix_rejects_before_dependencies_install_or_npm(tmp_path, monkeypatch, entry) -> None:
    monkeypatch.setattr(revideo_engine, "_require_revideo_deps", lambda: pytest.fail("dependency probe invoked"))
    monkeypatch.setattr(revideo_engine, "_install_validated", lambda *_a, **_k: pytest.fail("install invoked"))
    monkeypatch.setattr(revideo_engine, "_run_npm", lambda *_a, **_k: pytest.fail("npm invoked"))
    job = _job("mp4") | {"out_file": "video.MP4"}

    if entry == "staged":
        project = materialize_project(tmp_path / "bridge", _job("mp4"))
        (project / "src" / "job.json").write_text(json.dumps(job), encoding="utf-8")
        with pytest.raises(RevideoProjectError, match="job file is invalid"):
            render(project, str(tmp_path / "final.MP4"))
    else:
        with pytest.raises(ValidationError, match=r"job\.out_file"):
            render_job(job, str(tmp_path / "final.MP4"), work_dir=tmp_path / "work")


def _stub_bridge(tmp_path: Path, private_name: str) -> subprocess.CompletedProcess[str]:
    shutil.copyfile(revideo_engine.TEMPLATE_DIR / "render.mjs", tmp_path / "render.mjs")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "job.json").write_text(json.dumps(_job("mp4")), encoding="utf-8")
    renderer = tmp_path / "node_modules" / "@revideo" / "renderer"
    renderer.mkdir(parents=True)
    (renderer / "package.json").write_text('{"main":"index.cjs"}\n', encoding="utf-8")
    (renderer / "index.cjs").write_text(
        "module.exports.renderVideo = async (options) => {\n"
        "  console.log('CAPTURE:' + JSON.stringify(options));\n"
        "  return options.settings.outFile;\n"
        "};\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["node", "render.mjs"],
        cwd=tmp_path,
        env={**os.environ, revideo_engine._RUN_OUTPUT_ENV: private_name},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(("suffix", "exporter"), [("mp4", "mp4"), ("webm", "webm"), ("mov", "proRes")])
def test_javascript_bridge_selects_closed_exporter_map(tmp_path, suffix, exporter) -> None:
    result = _stub_bridge(tmp_path, f"private.{suffix}")

    assert result.returncode == 0, result.stderr
    captured = next(line for line in result.stdout.splitlines() if line.startswith("CAPTURE:"))
    settings = json.loads(captured.removeprefix("CAPTURE:"))["settings"]
    assert settings["outFile"] == f"private.{suffix}"
    assert settings["projectSettings"]["exporter"] == {
        "name": "@revideo/core/ffmpeg",
        "options": {"format": exporter},
    }


@pytest.mark.parametrize("private_name", ["private.MP4", "private.avi", "private"])
def test_javascript_bridge_rejects_unknown_private_suffix_before_renderer(tmp_path, private_name) -> None:
    result = _stub_bridge(tmp_path, private_name)

    assert result.returncode != 0
    assert "CAPTURE:" not in result.stdout
