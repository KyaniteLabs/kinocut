"""Offline tests for the two-phase release cutover."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "apply_public_release_cutover.py"
_SPEC = importlib.util.spec_from_file_location("apply_public_release_cutover", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
cutover = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cutover)


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_live_pypi_has_version_true() -> None:
    assert cutover.live_pypi_has_version("1.14.1", opener=lambda req, timeout: _FakeResp(200))


def test_live_pypi_has_version_404() -> None:
    def opener(req, timeout):
        raise HTTPError("https://pypi.org/pypi/kinocut/1.15.0/json", 404, "Not Found", {}, None)

    assert cutover.live_pypi_has_version("1.15.0", opener=opener) is False


def test_post_publish_require_live_blocks_missing_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cutover, "live_pypi_has_version", lambda version: False)
    monkeypatch.setattr(cutover, "ROOT", tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_public_release_cutover.py",
            "--phase",
            "post-publish",
            "--version",
            "2.1.0",
            "--previous-version",
            "2.0.1",
            "--mcp-video-version",
            "1.6.23",
            "--date",
            "2026-11-30",
            "--mcp-tools",
            "208",
            "--cli-commands",
            "178",
        ],
    )
    assert cutover.main() == 1


def test_prepare_phase_moves_only_candidate_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prepare runs before PyPI has the release: published-runtime pins must not move."""
    for relative in (
        "docs/public_claims.json",
        "pyproject.toml",
        "kinocut/__init__.py",
        "server.json",
        "npm/package.json",
        "npm/bin/kinocut.js",
        "compat/mcp-video-shim/pyproject.toml",
        "mcpb/manifest.json",
        "plugins/kinocut/plugin.json",
        "plugins/kinocut/mcp.json",
        "gemini-extension.json",
        cutover.VIDEO_CI_ACTION,
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "docs" / "public_claims.json").write_text(
        json.dumps({"published_version": "2.0.1", "release_candidate_version": "2.0.1"}), encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "2.0.1"\n', encoding="utf-8")
    (tmp_path / "kinocut" / "__init__.py").write_text('__version__ = "2.0.1"\n', encoding="utf-8")
    (tmp_path / "server.json").write_text(
        json.dumps({"version": "2.0.1", "packages": [{"version": "2.0.1"}]}), encoding="utf-8"
    )
    (tmp_path / "npm" / "package.json").write_text('{"name": "kinocut", "version": "2.0.1"}\n', encoding="utf-8")
    (tmp_path / "npm" / "bin" / "kinocut.js").write_text('"--from", "kinocut==2.0.1"', encoding="utf-8")
    (tmp_path / "compat" / "mcp-video-shim" / "pyproject.toml").write_text(
        'dependencies = ["kinocut==2.0.1"]\n', encoding="utf-8"
    )
    (tmp_path / "mcpb" / "manifest.json").write_text('{"version": "2.0.1"}\n', encoding="utf-8")
    (tmp_path / "plugins" / "kinocut" / "plugin.json").write_text('{"version": "2.0.1"}\n', encoding="utf-8")
    (tmp_path / "plugins" / "kinocut" / "mcp.json").write_text(
        '{"mcpServers": {"kinocut": {"args": ["kinocut==2.0.1"]}}}\n', encoding="utf-8"
    )
    (tmp_path / "gemini-extension.json").write_text('{"version": "2.0.1"}\n', encoding="utf-8")
    (tmp_path / cutover.VIDEO_CI_ACTION).write_text(
        'inputs:\n  kinocut_version:\n    default: "2.0.1"\n', encoding="utf-8"
    )
    monkeypatch.setattr(cutover, "ROOT", tmp_path)

    namespace = cutover.argparse.Namespace(
        phase="prepare",
        apply=True,
        version="2.1.0",
        previous_version="2.0.1",
        date="2026-11-30",
        mcp_tools=208,
        cli_commands=178,
        mcp_video_version="1.6.23",
        keep_dev_ahead=False,
        require_live=True,
    )
    cutover.prepare_phase(namespace, "2.1.0", "2.0.1")

    assert json.loads((tmp_path / "docs" / "public_claims.json").read_text())["release_candidate_version"] == "2.1.0"
    assert json.loads((tmp_path / "docs" / "public_claims.json").read_text())["published_version"] == "2.0.1"
    assert 'version = "2.1.0"' in (tmp_path / "pyproject.toml").read_text()
    assert json.loads((tmp_path / "server.json").read_text())["version"] == "2.1.0"
    assert "kinocut==2.1.0" in (tmp_path / "npm" / "bin" / "kinocut.js").read_text()
    assert "kinocut==2.1.0" in (tmp_path / "compat" / "mcp-video-shim" / "pyproject.toml").read_text()
    assert json.loads((tmp_path / "mcpb" / "manifest.json").read_text())["version"] == "2.1.0"
    # Published-runtime surfaces stay on the outgoing release until post-publish.
    assert json.loads((tmp_path / "plugins" / "kinocut" / "plugin.json").read_text())["version"] == "2.0.1"
    assert "kinocut==2.0.1" in (tmp_path / "plugins" / "kinocut" / "mcp.json").read_text()
    assert json.loads((tmp_path / "gemini-extension.json").read_text())["version"] == "2.0.1"
    assert 'default: "2.0.1"' in (tmp_path / cutover.VIDEO_CI_ACTION).read_text()


def test_post_publish_phase_moves_every_published_runtime_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-publish moves plugin manifests, launch pins, the CI action and delegates to the sweep."""
    for relative in (
        *cutover.PLUGIN_MANIFESTS,
        "gemini-extension.json",
        "smithery.yaml",
        cutover.VIDEO_CI_ACTION,
        "packaging/claude-plugin/pyproject.toml",
        "docs/public_claims.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for relative in cutover.PLUGIN_MANIFESTS:
        (tmp_path / relative).write_text(
            '{"version": "2.0.1", "mcpServers": {"kinocut": {"args": ["kinocut==2.0.1"]}}}\n', encoding="utf-8"
        )
    (tmp_path / "gemini-extension.json").write_text(
        '{"version": "2.0.1", "mcpServers": {"kinocut": {"args": ["kinocut==2.0.1"]}}}\n', encoding="utf-8"
    )
    (tmp_path / "smithery.yaml").write_text(
        'startCommand:\n  type: stdio\n  configSchema: {}\n  commandFunction:\n    (config) => ({ "command": "uvx", "args": ["kinocut==2.0.1"] })\n',
        encoding="utf-8",
    )
    (tmp_path / cutover.VIDEO_CI_ACTION).write_text(
        'inputs:\n  kinocut_version:\n    default: "2.0.1"\n', encoding="utf-8"
    )
    (tmp_path / "packaging" / "claude-plugin" / "pyproject.toml").write_text(
        'dependencies = ["kinocut==2.0.1"]\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "public_claims.json").write_text(
        json.dumps({"published_version": "2.0.1", "release_candidate_version": "2.1.0"}), encoding="utf-8"
    )
    monkeypatch.setattr(cutover, "ROOT", tmp_path)
    monkeypatch.setattr(cutover, "live_pypi_has_version", lambda version: True)
    sweep_calls: list[list[str]] = []

    def fake_call(cmd: list[str], cwd: Path | None = None) -> int:
        sweep_calls.append(cmd)
        return 0

    monkeypatch.setattr(cutover.subprocess, "call", fake_call)
    namespace = cutover.argparse.Namespace(
        phase="post-publish",
        apply=True,
        version="2.1.0",
        previous_version="2.0.1",
        date="2026-11-30",
        mcp_tools=208,
        cli_commands=178,
        mcp_video_version="1.6.23",
        keep_dev_ahead=False,
        require_live=True,
    )
    assert cutover.post_publish_phase(namespace, "2.1.0", "2.0.1") == 0

    for relative in cutover.PLUGIN_MANIFESTS:
        text = (tmp_path / relative).read_text()
        assert '"version": "2.1.0"' in text, relative
        assert "kinocut==2.1.0" in text, relative
    gemini = (tmp_path / "gemini-extension.json").read_text()
    assert '"version": "2.1.0"' in gemini and "kinocut==2.1.0" in gemini
    assert "kinocut==2.1.0" in (tmp_path / "smithery.yaml").read_text()
    assert 'default: "2.1.0"' in (tmp_path / cutover.VIDEO_CI_ACTION).read_text()
    assert "kinocut==2.1.0" in (tmp_path / "packaging" / "claude-plugin" / "pyproject.toml").read_text()
    claims = json.loads((tmp_path / "docs" / "public_claims.json").read_text())
    assert (claims["published_version"], claims["published_mcp_tools"], claims["published_cli_commands"]) == (
        "2.1.0",
        208,
        178,
    )
    # The current-pins sweep is invoked with the release pair and --apply.
    assert len(sweep_calls) == 1
    assert sweep_calls[0][-5:] == ["--kinocut", "2.1.0", "--mcp-video", "1.6.23", "--apply"]
    assert sweep_calls[0][1].endswith("scripts/sweep_install_pins.py")


def test_post_publish_phase_requires_the_shim_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cutover, "ROOT", tmp_path)
    monkeypatch.setattr(cutover, "live_pypi_has_version", lambda version: True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "public_claims.json").write_text("{}")
    for relative in (
        *cutover.PLUGIN_MANIFESTS,
        "gemini-extension.json",
        "smithery.yaml",
        cutover.VIDEO_CI_ACTION,
        "packaging/claude-plugin/pyproject.toml",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"version": "2.0.1"}\n' if path.suffix == ".json" else "", encoding="utf-8")
    namespace = cutover.argparse.Namespace(
        phase="post-publish",
        apply=False,
        version="2.1.0",
        previous_version="2.0.1",
        date="2026-11-30",
        mcp_tools=208,
        cli_commands=178,
        mcp_video_version=None,
        keep_dev_ahead=False,
        require_live=True,
    )
    assert cutover.post_publish_phase(namespace, "2.1.0", "2.0.1") == 1


def test_post_publish_phase_moves_the_opencode_javascript_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OpenCode host reads a JS helper, so the Python pin regexes cannot reach it.

    A release that skips this leaves the OpenCode plugin launching the outgoing
    runtime while every JSON manifest says the new one.
    """
    helper = tmp_path / cutover.OPENCODE_HELPER
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text('const RUNTIME_VERSION = "2.0.1";\n', encoding="utf-8")
    manifest = tmp_path / cutover.OPENCODE_MANIFEST
    manifest.write_text('{"command": ["uvx", "kinocut==2.0.1"]}\n', encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "public_claims.json").write_text("{}", encoding="utf-8")
    for relative in (*cutover.PLUGIN_MANIFESTS, "gemini-extension.json", "smithery.yaml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"version": "2.0.1"}\n', encoding="utf-8")
    (tmp_path / cutover.VIDEO_CI_ACTION).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / cutover.VIDEO_CI_ACTION).write_text('    default: "2.0.1"\n', encoding="utf-8")
    (tmp_path / "packaging" / "claude-plugin").mkdir(parents=True)
    (tmp_path / "packaging" / "claude-plugin" / "pyproject.toml").write_text(
        'dependencies = ["kinocut==2.0.1"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(cutover, "ROOT", tmp_path)
    monkeypatch.setattr(cutover, "live_pypi_has_version", lambda version: True)
    monkeypatch.setattr(cutover.subprocess, "call", lambda cmd, cwd=None: 0)
    namespace = cutover.argparse.Namespace(
        phase="post-publish",
        apply=True,
        version="2.1.0",
        previous_version="2.0.1",
        date="2026-11-30",
        mcp_tools=208,
        cli_commands=178,
        mcp_video_version="1.6.23",
        keep_dev_ahead=False,
        require_live=True,
    )

    assert cutover.post_publish_phase(namespace, "2.1.0", "2.0.1") == 0
    assert 'const RUNTIME_VERSION = "2.1.0";' in helper.read_text(encoding="utf-8")
    assert "kinocut==2.1.0" in manifest.read_text(encoding="utf-8")
