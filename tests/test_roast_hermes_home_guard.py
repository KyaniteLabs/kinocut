"""Roast K2/K3: under Hermes, outputs never land in the plugin folder or its home."""

from __future__ import annotations

import os

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_artifact_location


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "custom-hermes"
    plugin = home / "plugins" / "kinocut"
    plugin.mkdir(parents=True)
    (home / "config.yaml").write_text("model: x\n")
    monkeypatch.setenv("PLUGIN_ROOT", str(plugin))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    return home


def test_custom_hermes_home_is_refused_without_hermes_home_env(hermes_home):
    with pytest.raises(MCPVideoError, match="configured agent or application home"):
        _validate_artifact_location(str(hermes_home / "x.mp4"), "Output path")
    with pytest.raises(MCPVideoError, match="configured agent or application home"):
        _validate_artifact_location(str(hermes_home / "plugins" / "kinocut" / "icon.png"), "Output path")


def test_relative_output_under_hermes_is_refused_with_a_clear_reason(hermes_home, monkeypatch):
    monkeypatch.chdir(hermes_home / "plugins" / "kinocut")
    with pytest.raises(MCPVideoError, match="must be an absolute path"):
        _validate_artifact_location("rel2.mp4", "Output path")


def test_media_folder_outside_the_home_still_works(hermes_home, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    assert _validate_artifact_location(str(media / "out.mp4"), "Output path") == os.path.realpath(media / "out.mp4")


def test_plugin_root_outside_a_hermes_home_blocks_only_the_plugin(tmp_path, monkeypatch):
    plugin = tmp_path / "checkout" / "plugins" / "kinocut"
    plugin.mkdir(parents=True)
    monkeypatch.setenv("PLUGIN_ROOT", str(plugin))
    with pytest.raises(MCPVideoError):
        _validate_artifact_location(str(plugin / "x.mp4"), "Output path")
    out = tmp_path / "checkout" / "out.mp4"
    assert _validate_artifact_location(str(out), "Output path") == os.path.realpath(out)


def test_symlinked_plugin_root_also_protects_its_hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "custom-home"
    target_plugin = tmp_path / "worktree" / "plugins" / "kinocut"
    target_plugin.mkdir(parents=True)
    (home / "plugins").mkdir(parents=True)
    (home / "config.yaml").write_text("model: x\n")
    (home / "plugins" / "kinocut").symlink_to(target_plugin, target_is_directory=True)
    monkeypatch.setenv("PLUGIN_ROOT", str(home / "plugins" / "kinocut"))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    with pytest.raises(MCPVideoError, match="configured agent or application home"):
        _validate_artifact_location(str(home / "target.mp4"), "Output path")


def test_linked_plugin_data_path_protects_its_hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "custom-home"
    checkout_plugin = tmp_path / "worktree" / "plugins" / "kinocut"
    checkout_plugin.mkdir(parents=True)
    (home / "plugin-data" / "kinocut").mkdir(parents=True)
    (home / "config.yaml").write_text("model: x\n")
    monkeypatch.setenv("PLUGIN_ROOT", str(checkout_plugin))
    monkeypatch.setenv("PLUGIN_DATA", str(home / "plugin-data" / "kinocut"))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    with pytest.raises(MCPVideoError, match="configured agent or application home"):
        _validate_artifact_location(str(home / "target.mp4"), "Output path")


def test_relative_paths_still_work_outside_hermes(tmp_path, monkeypatch):
    monkeypatch.delenv("PLUGIN_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _validate_artifact_location("out.mp4", "Output path") == os.path.realpath(tmp_path / "out.mp4")
