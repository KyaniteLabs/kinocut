"""Distribution and compatibility contracts for the Kinocut rename."""

from __future__ import annotations

import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import mcp_video
import pytest


ROOT = Path(__file__).resolve().parents[1]
KINOCUT_VERSION = "1.16.4"
# Marketplace bundles consume the published registry release independently of
# this checkout's product version; reconciliation must preserve canonical code.
PLUGIN_RUNTIME_VERSION = "1.16.4"
SHIM_VERSION = "1.6.19"


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


def test_wheel_and_sdist_ship_complete_revideo_template(tmp_path) -> None:
    required = {
        "README.md",
        "package.json",
        "package-lock.json",
        "render.mjs",
        "tsconfig.json",
        "src/job.json",
        "src/project.ts",
        "src/scene.ts",
    }
    out_dir = tmp_path / "dist"
    if importlib.util.find_spec("build") is not None:
        command = [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(out_dir)]
    elif uv := shutil.which("uv"):
        command = [uv, "build", "--wheel", "--sdist", "--out-dir", str(out_dir), str(ROOT)]
    else:
        pytest.skip("Python build frontend is unavailable")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr

    wheel = next(out_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = set(archive.namelist())
    assert {f"kinocut/revideo_template/{name}" for name in required} <= wheel_files

    sdist = next(out_dir.glob("*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_files = {name.partition("/")[2] for name in archive.getnames()}
    assert {f"kinocut/revideo_template/{name}" for name in required} <= sdist_files


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
    claims = json.loads((ROOT / "docs" / "public_claims.json").read_text(encoding="utf-8"))
    published = claims["published_version"]
    candidate = claims["release_candidate_version"]

    assert shim["project"]["name"] == "mcp-video"
    assert shim["project"]["version"] == SHIM_VERSION
    # Apache-2.0 §4(a): the shim declares Apache-2.0, so the license text must
    # ship with it — vendored next to the pyproject and byte-identical to the
    # repository license, with a licence section in the shipped README.
    assert shim["project"]["license"] == "Apache-2.0"
    assert (ROOT / "compat" / "mcp-video-shim" / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert "## License" in (ROOT / "compat" / "mcp-video-shim" / "README.md").read_text(encoding="utf-8")
    # Mid-cutover: the published shim must pin the live PyPI kinocut, not an
    # arbitrary version, or `pip install mcp-video` asks for an unpublished wheel.
    # During a staged release window (release-prep landed, tag not yet cut) the
    # in-repo shim may pin the release candidate instead: the shim publishes
    # simultaneously with the release via .github/workflows/publish.yml, which
    # itself requires candidate pins at tag time, so candidate pins never reach
    # PyPI ahead of the kinocut wheel they name.
    allowed_pins = ([f"kinocut=={published}"], [f"kinocut=={candidate}"])
    assert shim["project"]["dependencies"] in allowed_pins
    # The canonical dependency owns all aliases. A duplicate shim entry point
    # makes uninstalling the metadata-only shim delete Kinocut's executable.
    assert "scripts" not in shim["project"]
    assert shim["tool"]["hatch"]["build"]["targets"]["wheel"]["bypass-selection"] is True
    assert not (ROOT / "compat" / "mcp-video-shim" / "mcp_video").exists()

    canonical_extras = canonical["project"]["optional-dependencies"]
    shim_extras = shim["project"]["optional-dependencies"]
    assert set(shim_extras) == set(canonical_extras)
    for extra in canonical_extras:
        assert shim_extras[extra] in (
            [f"kinocut[{extra}]=={published}"],
            [f"kinocut[{extra}]=={candidate}"],
        )


def test_shim_sdist_and_wheel_ship_the_apache_license_text(tmp_path) -> None:
    """Apache-2.0 §4(a): the license copy must accompany the distribution."""
    shim_dir = ROOT / "compat" / "mcp-video-shim"
    out_dir = tmp_path / "dist"
    if importlib.util.find_spec("build") is not None:
        command = [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(out_dir), str(shim_dir)]
    elif uv := shutil.which("uv"):
        command = [uv, "build", "--wheel", "--sdist", "--out-dir", str(out_dir), str(shim_dir)]
    else:
        pytest.skip("Python build frontend is unavailable")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr

    license_bytes = (ROOT / "LICENSE").read_bytes()

    sdist = next(out_dir.glob("mcp_video-*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        member = f"mcp_video-{SHIM_VERSION}/LICENSE"
        names = archive.getnames()
        assert member in names, names
        assert archive.extractfile(member).read() == license_bytes

    wheel = next(out_dir.glob("mcp_video-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        shipped = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
        assert shipped, names
        assert archive.read(shipped[0]) == license_bytes
        dist_info = shipped[0].rsplit("/licenses/LICENSE", 1)[0]
        metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8")
    assert "License-File: LICENSE" in metadata


def test_npm_package_is_a_thin_uvx_bootstrap_not_a_second_runtime() -> None:
    package = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    launcher = (ROOT / "npm" / "bin" / "kinocut.js").read_text(encoding="utf-8")

    assert package["name"] == "kinocut"
    assert package["version"] == KINOCUT_VERSION
    assert package["bin"] == {"kino": "bin/kinocut.js", "kinocut": "bin/kinocut.js"}
    # Apache-2.0 §4(a): the declared license text must accompany the tarball.
    # `files` whitelists exactly what `npm pack` ships, so LICENSE must be
    # both listed here and present in npm/ byte-identical to the repo license.
    assert package["license"] == "Apache-2.0"
    assert "LICENSE" in package["files"]
    assert (ROOT / "npm" / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert f"kinocut=={KINOCUT_VERSION}" in launcher
    assert "uvx" in launcher
    assert "process.argv.slice(2)" in launcher
    assert "ffmpeg" not in package.get("dependencies", {})


def test_registry_metadata_uses_the_new_immutable_identity() -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert server["name"] == "tech.kyanitelabs/kinocut"
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
    # MCPB operator docs stay in-repo (docs/MCPB.md) but are not shipped under /docs/
    # in the sdist — publish artifact checks forbid that path.
    assert {"/mcpb", "/scripts/build-mcpb.py"} <= sdist_includes
    assert project["tool"]["hatch"]["build"]["targets"]["sdist"]["force-include"] == {"mcpb/icon.png": "mcpb/icon.png"}
    assert "/docs/MCPB.md" not in sdist_includes
    assert "/kinocut_sound" in sdist_includes
    assert '["-m", "kinocut", "--mcp"]' in launcher
    assert "shell: false" in launcher
    assert 'require("node:child_process")' in launcher
    assert "\nimport " not in launcher
    assert "env.PATH =" not in launcher
    assert "KINOCUT_FFMPEG_EXECUTABLE" in launcher
    assert "KINOCUT_FFPROBE_EXECUTABLE" in launcher
    assert "MCPB does not bundle Python, Kinocut, FFmpeg, Node, Hyperframes, or AI model weights" in docs
    assert "directory fields" not in docs
    assert "enableOptionalAi" not in docs
    assert "Staged Release Gates Before External Publication" in docs
    assert "user-configured-local-access" in docs

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
        assert sorted(archive.namelist()) == ["README.md", "icon.png", "manifest.json", "server/launcher.js"]
        assert archive.read("icon.png") == (ROOT / "mcpb/icon.png").read_bytes()
        packed_manifest = json.loads(archive.read("manifest.json"))
    assert packed_manifest == manifest


def test_mcpb_launcher_is_compatible_with_the_declared_node_floor() -> None:
    npx = shutil.which("npx")
    if npx is None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node 18 and npx are unavailable")
        command = [node]
    else:
        systems = {"darwin": "darwin", "linux": "linux", "win32": "win"}
        architectures = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}
        system = systems.get(sys.platform)
        architecture = architectures.get(platform.machine().lower())
        if system is None or architecture is None or (system == "win" and architecture == "arm64"):
            pytest.skip("No Node 18 binary package for this platform")
        # Direct binary packages have no lifecycle installer. The node@18
        # wrapper's nested npm install is incompatible with npm 11's script policy.
        prefix = "node-bin" if (system, architecture) == ("darwin", "arm64") else "node"
        package = f"{prefix}-{system}-{architecture}@18.20.8"
        command = [npx, "--yes", f"--package={package}", "--", "node"]
    version = subprocess.run([*command, "--version"], capture_output=True, text=True, check=False, timeout=60)
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip().startswith("v18."), "The Node 18 floor must be checked with Node 18"
    result = subprocess.run(
        [*command, "--check", str(ROOT / "mcpb" / "server" / "launcher.js")],
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
    assert "for shim_version in 1.6.0 1.6.14" in workflow
    assert '"mcp-video==$shim_version"' in workflow
    assert "--force-reinstall --no-deps" in workflow
    assert '"$upgrade_bin/pip" uninstall --yes mcp-video' in workflow
    assert "RELEASE_ATTEMPT" not in workflow
    assert "already exists and matches the requested release; publication will skip it" in workflow
    assert "group: kinocut-publish" in workflow
    assert "cancel-in-progress: false" in workflow
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


def _workflow_job(workflow: str, name: str) -> str:
    start = re.search(rf"^  {re.escape(name)}:\n", workflow, re.MULTILINE)
    assert start is not None, name
    following = re.search(r"^  [a-z][a-z0-9-]*:\n", workflow[start.end() :], re.MULTILINE)
    end = start.end() + following.start() if following is not None else len(workflow)
    return workflow[start.start() : end]


def test_release_and_pages_use_hosted_runners_and_one_clean_wheel_gate() -> None:
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "pull_request:" not in publish.split("permissions:", 1)[0]
    assert "blacksmith" not in _workflow_job(publish, "surface-audit").lower()
    assert "runs-on: ubuntu-24.04" in _workflow_job(publish, "surface-audit")
    build = _workflow_job(publish, "build")
    assert "runs-on: ubuntu-24.04" in build
    assert "timeout-minutes: 45" in build
    assert build.count("scripts/verify_onboarding_release.py") == 1
    assert build.index("scripts/verify_onboarding_release.py") < build.index("Upload Python artifacts")
    assert "runs-on: ubuntu-24.04" in _workflow_job(pages, "deploy")
    assert "blacksmith" not in pages.lower()


def test_release_recovery_authority_boundaries_are_unchanged() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    pypi = _workflow_job(workflow, "publish")
    npm = _workflow_job(workflow, "publish-npm")
    recovery = _workflow_job(workflow, "publish-npm-recovery")
    registry = _workflow_job(workflow, "publish-mcp-registry")
    assert "needs: build" in pypi and "environment: pypi" in pypi and "id-token: write" in pypi
    assert "needs: publish" in npm and "environment: npm" in npm and "id-token: write" in npm
    assert "if: github.event_name == 'workflow_dispatch'" in recovery
    assert "environment: npm" in recovery and "id-token: write" in recovery
    assert "needs: [publish, publish-npm, publish-npm-recovery]" in registry
    assert "needs.publish-npm-recovery.result == 'success'" in registry
    assert "github.event_name == 'workflow_dispatch'" in registry
    assert "id-token: write" in registry


def test_integration_smoke_adds_nonpublishing_exact_head_onboarding_job() -> None:
    workflow = (ROOT / ".github" / "workflows" / "integration-smoke.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:\n    branches: [master]" in workflow
    assert "pull_request:" in workflow
    job = _workflow_job(workflow, "clean-wheel-onboarding")
    assert "if: github.event_name != 'push'" in job
    assert "runs-on: ubuntu-24.04" in job
    assert "timeout-minutes: 30" in job
    assert '$2 == "subtitles" && $3 == "V->V"' in job
    assert "github.event.pull_request.head.sha || github.sha" in job
    assert job.count("scripts/verify_onboarding_release.py") == 1
    forbidden = (
        "environment:",
        "id-token: write",
        "NPM_TOKEN",
        "PYPI",
        "npm publish",
        "mcp-publisher",
        "upload-artifact",
    )
    assert all(token not in job for token in forbidden)
    for existing in ("base-cli-and-doctor", "ffmpeg-smoke", "image-extra-smoke", "ai-module-smoke"):
        smoke = _workflow_job(workflow, existing)
        assert "runs-on: ubuntu-24.04" in smoke
        assert "python -m venv .venv" in smoke


def test_vendor_plugin_bundle_versions_and_pinned_runtime_are_consistent() -> None:
    """The plugin bundle can advance without republishing its pinned runtime."""
    version = PLUGIN_RUNTIME_VERSION
    plugin = ROOT / "plugins" / "kinocut"
    plugin_version = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin_version)
    for rel in (
        "plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".minimax-plugin/plugin.json",
        "kimi.plugin.json",
    ):
        assert json.loads((plugin / rel).read_text(encoding="utf-8"))["version"] == plugin_version, rel
    marketplace = json.loads((ROOT / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == "kinocut" and ROOT / entry["source"] == plugin
    cursor = json.loads((plugin / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (plugin / cursor["mcpServers"]).is_file()
    cursor_server = json.loads((plugin / cursor["mcpServers"]).read_text())["mcpServers"]["kinocut"]
    assert cursor_server == {"type": "stdio", "command": "uvx", "args": [f"kinocut=={version}"]}
    assert {p.parent.name for p in (plugin / cursor["skills"]).glob("*/SKILL.md")} == {"kinocut", "kinocut-repurpose"}
    for rel in ("mcp.json", "kinocut.mcp.json", "kimi.plugin.json"):
        server = json.loads((plugin / rel).read_text(encoding="utf-8"))["mcpServers"]["kinocut"]
        assert server["command"] == "uvx" and server["args"] == [f"kinocut=={version}"], rel
    assert f'"kinocut=={version}"' in (plugin / "opencode-plugin" / "README.md").read_text(encoding="utf-8")
    gemini = json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
    assert gemini["version"] == version
    assert gemini["mcpServers"]["kinocut"] == {"command": "uvx", "args": [f"kinocut=={version}"]}


def test_claude_plugin_plain_pinned_launcher_has_a_complete_public_registry_lock() -> None:
    plugin = ROOT / "plugins" / "kinocut"
    locked = ROOT / "packaging" / "claude-plugin"
    assert not (plugin / "pyproject.toml").exists() and not (plugin / "uv.lock").exists()
    project = _toml(locked / "pyproject.toml")["project"]
    lock = _toml(locked / "uv.lock")
    server = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["kinocut"]

    assert project["dependencies"] == [f"kinocut=={PLUGIN_RUNTIME_VERSION}"]
    assert project["requires-python"] == lock["requires-python"] == ">=3.11"
    assert project["version"] == json.loads((plugin / ".claude-plugin/plugin.json").read_text())["version"]
    assert server == {"command": "uvx", "args": [f"kinocut=={PLUGIN_RUNTIME_VERSION}"]}
    packages = {package["name"]: package for package in lock["package"]}
    assert packages["kinocut"]["version"] == PLUGIN_RUNTIME_VERSION
    assert packages[project["name"]]["source"] == {"virtual": "."}
    for package in lock["package"]:
        if package["name"] == project["name"]:
            continue
        assert package["source"] == {"registry": "https://pypi.org/simple"}
        assert re.fullmatch(r"\d[^\s]*", package["version"]), package["name"]
        artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
        assert artifacts, package["name"]
        for artifact in artifacts:
            assert artifact["url"].startswith("https://files.pythonhosted.org/")
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["hash"])
        assert all(dependency["name"] in packages for dependency in package.get("dependencies", []))
    assert (locked / "uv.lock").stat().st_size < 256 * 1024


def test_registry_metadata_is_local_package_only() -> None:
    """KinoCut is distributed as a local stdio package, never as a hosted service."""
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert "remotes" not in server, "server.json must not advertise a hosted remote"
    packages = server.get("packages") or []
    assert [(p.get("registryType"), p.get("identifier"), p.get("transport", {}).get("type")) for p in packages] == [
        ("pypi", "kinocut", "stdio")
    ]
