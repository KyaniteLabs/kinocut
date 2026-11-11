"""State dirs follow KINOCUT_DATA_DIR, and fall back to the legacy home paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut import data_dirs


def test_default_is_the_legacy_home_path(monkeypatch, tmp_path):
    monkeypatch.delenv("KINOCUT_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert data_dirs.crush_home() == tmp_path / ".mcp-video"
    assert data_dirs.cache_home() == tmp_path / ".cache" / "mcp-video"


def test_env_override_moves_both(monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_DATA_DIR", str(tmp_path / "plugin-data"))
    assert data_dirs.crush_home() == tmp_path / "plugin-data"
    assert data_dirs.cache_home() == tmp_path / "plugin-data" / "cache"


def test_blank_override_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_DATA_DIR", "  ")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert data_dirs.cache_home() == tmp_path / ".cache" / "mcp-video"


def test_modules_use_the_resolver(monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.delenv("MCP_VIDEO_CRUSH_PATH", raising=False)
    from kinocut import engine_glitch_shader, font_manager

    assert font_manager._font_cache_dir() == str(tmp_path / "d" / "cache" / "fonts")
    crush = tmp_path / "d" / "crush-js" / "src"
    crush.mkdir(parents=True)
    assert engine_glitch_shader._resolve_crush_path() == str(crush)


def test_relative_override_is_made_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KINOCUT_DATA_DIR", "rel-data")
    assert data_dirs.crush_home().is_absolute()
    assert data_dirs.crush_home() == (tmp_path / "rel-data").resolve()
    assert data_dirs.cache_home() == (tmp_path / "rel-data").resolve() / "cache"
