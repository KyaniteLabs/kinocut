"""Launch-remediation regression tests."""

from __future__ import annotations

import builtins
import logging
import runpy
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest


def test_mograph_frame_count_is_capped(monkeypatch):
    from mcp_video.server_tools_effects import video_mograph_count

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("mograph engine should not run for oversized requests")

    import mcp_video.effects_engine

    monkeypatch.setattr(mcp_video.effects_engine, "mograph_count", should_not_run)

    result = video_mograph_count(0, 100, duration=10_000, output_path="counter.mp4", fps=120)

    assert result["success"] is False
    assert result["error"]["code"] == "mograph_too_large"


def test_hyperframes_command_uses_local_pinned_binary(monkeypatch, tmp_path):
    from mcp_video import hyperframes_engine

    project = tmp_path / "project"
    project.mkdir()
    (project / "index.html").write_text("<html></html>")
    local_bin = project / "node_modules" / ".bin" / "hyperframes"
    local_bin.parent.mkdir(parents=True)
    local_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    local_bin.chmod(0o755)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stdout = "[]"
            stderr = ""

        return Result()

    monkeypatch.setattr(hyperframes_engine.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr(hyperframes_engine.subprocess, "run", fake_run)

    hyperframes_engine.compositions(str(project))

    assert captured["cmd"][:2] == [str(local_bin), "compositions"]
    assert "npx" not in captured["cmd"]
    assert "--no-install" not in captured["cmd"]


def test_ytdlp_rejects_resolved_private_media_url(monkeypatch, tmp_path):
    import sys
    import types

    from mcp_video.ai_engine.download import _download_with_ytdlp
    from mcp_video.errors import MCPVideoError

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert self.opts["proxy"] == ""
            assert download is False
            return {
                "id": "unsafe",
                "ext": "mp4",
                "requested_downloads": [{"url": "http://127.0.0.1/internal.mp4"}],
            }

        def prepare_filename(self, _info):
            return str(Path(tmp_path) / "unsafe.mp4")

    fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)

    with pytest.raises(MCPVideoError) as exc_info:
        _download_with_ytdlp("https://youtube.com/watch?v=unsafe", str(tmp_path))

    assert exc_info.value.code == "ssrf_blocked"


def test_built_artifact_checker_rejects_dogfood_media_and_repo_metadata(tmp_path):
    checker = runpy.run_path(".github/scripts/check-built-artifacts.py")
    archive = tmp_path / "mcp_video-9.9.9.tar.gz"

    with tarfile.open(archive, "w:gz") as tf:
        for name, body in {
            "mcp_video-9.9.9/mcp_video/__init__.py": b"",
            "mcp_video-9.9.9/dogfood_artifacts/showcase.mp4": b"media",
            "mcp_video-9.9.9/.git/config": b"repo",
            "mcp_video-9.9.9/.github/workflows/publish.yml": b"ci",
            "mcp_video-9.9.9/uv.lock": b"lock",
            "mcp_video-9.9.9/og-social-preview.png": b"image",
            "mcp_video-9.9.9/.coverage": b"coverage",
        }.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            tf.add(path, arcname=name)

    offenders = checker["find_offenders"](archive)

    assert "mcp_video-9.9.9/dogfood_artifacts/showcase.mp4" in offenders
    assert "mcp_video-9.9.9/.git/config" in offenders
    assert "mcp_video-9.9.9/.github/workflows/publish.yml" in offenders
    assert "mcp_video-9.9.9/uv.lock" in offenders
    assert "mcp_video-9.9.9/og-social-preview.png" in offenders
    assert "mcp_video-9.9.9/.coverage" in offenders


def test_built_artifact_checker_accepts_package_only_wheel(tmp_path):
    checker = runpy.run_path(".github/scripts/check-built-artifacts.py")
    wheel = tmp_path / "mcp_video-9.9.9-py3-none-any.whl"

    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("mcp_video/__init__.py", "")
        zf.writestr("mcp_video-9.9.9.dist-info/METADATA", "Name: mcp-video\n")

    assert checker["find_offenders"](wheel) == []


def test_built_artifact_checker_normalizes_wheel_root_paths(tmp_path):
    checker = runpy.run_path(".github/scripts/check-built-artifacts.py")
    wheel = tmp_path / "mcp_video-9.9.9-py3-none-any.whl"

    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("mcp_video/__init__.py", "")
        zf.writestr(".github/workflows/publish.yml", "")
        zf.writestr("dogfood_artifacts/showcase.mp4", "")

    offenders = checker["find_offenders"](wheel)

    assert ".github/workflows/publish.yml" in offenders
    assert "dogfood_artifacts/showcase.mp4" in offenders


def test_sdist_only_include_agrees_with_artifact_checker():
    checker = runpy.run_path(".github/scripts/check-built-artifacts.py")
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    includes = config["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    offenders = [
        entry
        for entry in includes
        if any(
            fragment in f"/{entry.lstrip('/')}"
            for fragment in checker["FORBIDDEN_SUBSTRINGS"]
        )
    ]

    assert offenders == []


def test_text_measurement_quietly_uses_fallback_without_pillow(monkeypatch, caplog):
    from mcp_video.effects_engine import text as text_engine

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with caplog.at_level(logging.WARNING):
        width, height = text_engine._measure_text("fallback", "Arial", 40)

    assert width > 0
    assert height > 0
    assert "PIL text measurement failed" not in caplog.text
