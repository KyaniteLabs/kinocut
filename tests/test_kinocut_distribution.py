"""Distribution and compatibility contracts for the Kinocut rename."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import mcp_video


ROOT = Path(__file__).resolve().parents[1]
KINOCUT_VERSION = "1.8.0"
SHIM_VERSION = "1.6.2"


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_kinocut_is_the_canonical_distribution_with_compatible_commands() -> None:
    project = _toml(ROOT / "pyproject.toml")

    assert project["project"]["name"] == "kinocut"
    assert project["project"]["version"] == KINOCUT_VERSION
    assert project["project"]["scripts"] == {
        "kino": "kinocut.__main__:main",
        "kinocut": "kinocut.__main__:main",
        "mcp-video": "kinocut.__main__:main",
    }
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["kinocut", "kinocut_sound"]
    assert wheel["force-include"] == {"mcp_video.py": "mcp_video.py"}


def test_kinocut_import_is_a_public_facade_over_the_compatible_runtime() -> None:
    import importlib
    import importlib.resources

    import kinocut
    from kinocut.errors import MCPVideoError as KinocutError
    import kinocut.models as kinocut_models
    from kinocut.models import EditResult as KinocutEditResult
    from mcp_video.errors import MCPVideoError as LegacyError
    import mcp_video.models as legacy_models
    from mcp_video.models import EditResult as LegacyEditResult

    assert kinocut.__version__ == KINOCUT_VERSION
    assert mcp_video.__version__ == KINOCUT_VERSION
    assert kinocut.Client is mcp_video.Client
    assert Path(mcp_video.__file__).name == "mcp_video.py"
    assert list(mcp_video.__path__) == list(kinocut.__path__)
    assert LegacyError is KinocutError
    assert LegacyEditResult is KinocutEditResult
    assert legacy_models is kinocut_models
    assert legacy_models.__spec__.name == "kinocut.models"
    assert legacy_models.__package__ == "kinocut"
    legacy_handler = importlib.import_module("mcp_video.cli.handlers_core")
    canonical_handler = importlib.import_module("kinocut.cli.handlers_core")
    assert legacy_handler is canonical_handler
    assert legacy_handler.__spec__.name == "kinocut.cli.handlers_core"
    assert legacy_handler.__package__ == "kinocut.cli"
    legacy_style = importlib.resources.files("mcp_video").joinpath("creation_templates/style.md")
    canonical_style = importlib.resources.files("kinocut").joinpath("creation_templates/style.md")
    assert legacy_style.read_bytes() == canonical_style.read_bytes()
    assert not (ROOT / "mcp_video").exists()


def test_python_module_launchers_run_the_canonical_cli() -> None:
    for module_name in ("kinocut", "mcp_video"):
        result = subprocess.run(
            [sys.executable, "-m", module_name, "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"Kinocut {KINOCUT_VERSION}"


def test_mcp_video_shim_is_metadata_only_and_forwards_every_extra() -> None:
    canonical = _toml(ROOT / "pyproject.toml")
    shim = _toml(ROOT / "compat" / "mcp-video-shim" / "pyproject.toml")

    assert shim["project"]["name"] == "mcp-video"
    assert shim["project"]["version"] == SHIM_VERSION
    assert shim["project"]["dependencies"] == [f"kinocut=={KINOCUT_VERSION}"]
    assert shim["project"]["scripts"] == {"mcp-video": "kinocut.__main__:main"}
    assert shim["tool"]["hatch"]["build"]["targets"]["wheel"]["bypass-selection"] is True
    assert not (ROOT / "compat" / "mcp-video-shim" / "mcp_video").exists()

    canonical_extras = canonical["project"]["optional-dependencies"]
    shim_extras = shim["project"]["optional-dependencies"]
    assert set(shim_extras) == set(canonical_extras)
    for extra in canonical_extras:
        assert shim_extras[extra] == [f"kinocut[{extra}]=={KINOCUT_VERSION}"]


def test_npm_package_is_a_thin_uvx_bootstrap_not_a_second_runtime() -> None:
    package = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    launcher = (ROOT / "npm" / "bin" / "kinocut.js").read_text(encoding="utf-8")

    assert package["name"] == "kinocut"
    assert package["version"] == KINOCUT_VERSION
    assert package["bin"] == {"kino": "bin/kinocut.js", "kinocut": "bin/kinocut.js"}
    assert f"kinocut=={KINOCUT_VERSION}" in launcher
    assert "uvx" in launcher
    assert "process.argv.slice(2)" in launcher
    assert "ffmpeg" not in package.get("dependencies", {})


def test_registry_metadata_uses_the_new_immutable_identity() -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert server["name"] == "io.github.KyaniteLabs/kinocut"
    assert server["title"] == "Kinocut"
    assert server["version"] == KINOCUT_VERSION
    assert len(server["description"]) <= 100
    assert server["websiteUrl"] == "https://kinocut.dev/"
    assert server["repository"]["url"] == "https://github.com/KyaniteLabs/kinocut"
    assert server["packages"] == [
        {
            "registryType": "pypi",
            "identifier": "kinocut",
            "version": KINOCUT_VERSION,
            "runtimeHint": "uvx",
            "transport": {"type": "stdio"},
        }
    ]


def test_mcpb_distribution_is_truthful_and_buildable(tmp_path) -> None:
    project = _toml(ROOT / "pyproject.toml")
    manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    launcher = (ROOT / "mcpb" / "server" / "launcher.js").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "MCPB.md").read_text(encoding="utf-8")

    assert manifest["$schema"].endswith("mcpb-manifest-v0.4.schema.json")
    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "kinocut"
    assert manifest["version"] == KINOCUT_VERSION
    assert manifest["repository"] == {"type": "git", "url": "https://github.com/KyaniteLabs/kinocut"}
    assert manifest["server"] == {
        "type": "node",
        "entry_point": "server/launcher.js",
        "mcp_config": {
            "command": "node",
            "args": ["${__dirname}/server/launcher.js"],
            "env": {
                "KINOCUT_MCPB_PYTHON": "${user_config.pythonExecutable}",
                "KINOCUT_MCPB_FFMPEG": "${user_config.ffmpegPath}",
                "MCP_VIDEO_HYPERFRAMES_COMMAND": "${user_config.hyperframesCommand}",
            },
        },
    }
    assert manifest["compatibility"]["runtimes"] == {"node": ">=18"}
    assert manifest["tools_generated"] is True
    assert "workspaceRoot" not in manifest["user_config"]
    assert "outputRoot" not in manifest["user_config"]
    assert manifest["user_config"]["pythonExecutable"]["required"] is False
    assert "enableOptionalAi" not in manifest["user_config"]
    sdist_includes = set(project["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"])
    assert {"/mcpb", "/docs/MCPB.md", "/scripts/build-mcpb.py"} <= sdist_includes
    assert "/kinocut_sound" in sdist_includes
    assert '["-m", "kinocut", "--mcp"]' in launcher
    assert "shell: false" in launcher
    assert 'require("node:child_process")' in launcher
    assert "import " not in launcher
    assert "env.PATH =" not in launcher
    assert "KINOCUT_FFMPEG_EXECUTABLE" in launcher
    assert "KINOCUT_FFPROBE_EXECUTABLE" in launcher
    assert "MCPB does not bundle Python, Kinocut, FFmpeg, Node, Hyperframes, or AI model weights" in docs
    assert "directory fields" not in docs
    assert "enableOptionalAi" not in docs
    assert "Release Gate Before External Publication" in docs
    assert "staged/local-only" in docs

    out_dir = tmp_path / "dist"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build-mcpb.py"), "--output-dir", str(out_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    bundle = out_dir / f"kinocut-{KINOCUT_VERSION}.mcpb"
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as archive:
        assert sorted(archive.namelist()) == ["README.md", "manifest.json", "server/launcher.js"]
        packed_manifest = json.loads(archive.read("manifest.json"))
    assert packed_manifest == manifest


def test_mcpb_launcher_is_compatible_with_the_declared_node_floor() -> None:
    npx = shutil.which("npx")
    if npx is None:
        result = subprocess.run(
            ["node", "--check", str(ROOT / "mcpb" / "server" / "launcher.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        result = subprocess.run(
            [npx, "--yes", "node@18", "--check", str(ROOT / "mcpb" / "server" / "launcher.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    assert result.returncode == 0, result.stderr


def test_mcpb_launcher_rejects_unsafe_ffmpeg_configuration() -> None:
    launcher = (ROOT / "mcpb" / "server" / "launcher.js").read_text(encoding="utf-8")

    assert "function configureFfmpeg" in launcher
    assert "basename(ffmpegPath)" in launcher
    assert "ffprobe" in launcher
    assert "process.exit(126)" in launcher
    assert "env.PATH =" not in launcher


def test_mcpb_ffmpeg_env_is_resolved_without_path_search(tmp_path, monkeypatch) -> None:
    import kinocut.engine_runtime_utils as runtime

    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    ffmpeg = tmp_path / ffmpeg_name
    ffprobe = tmp_path / ffprobe_name
    ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ffprobe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ffmpeg.chmod(0o755)
    ffprobe.chmod(0o755)
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", str(ffmpeg))
    monkeypatch.setenv("KINOCUT_FFPROBE_EXECUTABLE", str(ffprobe))
    monkeypatch.setattr(runtime.shutil, "which", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    monkeypatch.setattr(runtime, "_FFMPEG", "")
    monkeypatch.setattr(runtime, "_FFPROBE", "")

    assert runtime._ffmpeg() == str(ffmpeg)
    assert runtime._ffprobe() == str(ffprobe)


def test_mcpb_manifest_has_no_unenforced_root_or_ai_security_contracts() -> None:
    manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    rendered = json.dumps(manifest)

    assert "workspaceRoot" not in rendered
    assert "outputRoot" not in rendered
    assert "ALLOWED_ROOT" not in rendered
    assert "ENABLE_OPTIONAL_AI" not in rendered
    assert "enableOptionalAi" not in rendered


def test_release_workflow_builds_and_publishes_canonical_shim_and_npm_packages() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "compat/mcp-video-shim" in workflow
    assert "mcp-video/{shim_version}/json" in workflow
    assert "kinocut/{version}/json" in workflow
    assert "npm pack" in workflow
    assert "npm publish" in workflow
    assert "--provenance" in workflow
    assert "Verify clean install and mcp-video upgrade compatibility" in workflow
    assert "mcp-video==1.6.0" in workflow
    assert "pip uninstall --yes mcp-video" in workflow
    assert "RELEASE_ATTEMPT: ${{ github.run_attempt }}" in workflow
    assert "skip-existing: true" in workflow
    assert re.search(r"publish-npm:\n(?:.*\n)*?    needs: publish\n", workflow)
    assert 'npm view "kinocut@$version" version' in workflow
    assert "needs: [publish, publish-npm, publish-npm-recovery]" in workflow
    assert "needs.publish-npm.result == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "build-mcpb.py" not in workflow


def test_npm_publish_uses_local_tarball_and_has_oidc_recovery_dispatch() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "npm publish ./npm-dist/kinocut-*.tgz --provenance --access public" in workflow
    assert "publish-npm-recovery:" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "needs.publish-npm-recovery.result == 'success'" in workflow
