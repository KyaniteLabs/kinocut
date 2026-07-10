"""Distribution and compatibility contracts for the Kinocut rename."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import mcp_video


ROOT = Path(__file__).resolve().parents[1]
KINOCUT_VERSION = "1.7.0"
SHIM_VERSION = "1.6.1"


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
    assert wheel["packages"] == ["kinocut"]
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
    assert "needs: [publish, publish-npm]" in workflow
    assert "needs.publish-npm.result == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
