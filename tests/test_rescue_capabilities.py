"""Side-effect-free capability discovery for the rescue pipeline."""

from __future__ import annotations

import importlib.util

from mcp_video.rescue.capabilities import snapshot_capabilities


def test_snapshot_never_loads_missing_whisper():
    result = snapshot_capabilities(
        which=lambda name: f"/bin/{name}",
        find_spec=lambda name: None,
        package_version=lambda name: "must-not-be-called",
    )

    assert result["local_only"] is True
    assert result["whisper"] == {
        "available": False,
        "version": None,
        "executor": "openai-whisper",
    }


def test_snapshot_resolves_default_whisper_probe_at_call_time(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    result = snapshot_capabilities(which=lambda name: None)

    assert result["whisper"]["available"] is False


def test_snapshot_requires_both_ffmpeg_binaries():
    result = snapshot_capabilities(
        which=lambda name: "/bin/ffmpeg" if name == "ffmpeg" else None,
        find_spec=lambda name: None,
    )

    assert result["ffmpeg"]["available"] is False
    assert result["ffmpeg"]["ffmpeg"] is True
    assert result["ffmpeg"]["ffprobe"] is False


def test_snapshot_reads_whisper_version_without_importing_it():
    requested: list[str] = []

    result = snapshot_capabilities(
        which=lambda name: None,
        find_spec=lambda name: object(),
        package_version=lambda name: requested.append(name) or "20250625",
    )

    assert requested == ["openai-whisper"]
    assert result["whisper"]["available"] is True
    assert result["whisper"]["version"] == "20250625"
