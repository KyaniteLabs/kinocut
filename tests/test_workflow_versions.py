"""Version evidence must identify the selected executable and recover failures."""

import os
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from kinocut import engine_runtime_utils
from kinocut.rescue.capabilities import snapshot_capabilities
from kinocut.rescue import capabilities
from kinocut.workflow import _versions


@pytest.fixture
def native_binaries(monkeypatch):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg required")
    monkeypatch.setattr(_versions, "_ffmpeg_version_cache", None)
    monkeypatch.setattr(engine_runtime_utils, "_FFMPEG", "")
    monkeypatch.setattr(engine_runtime_utils, "_FFPROBE", "")
    return ffmpeg, ffprobe


def test_blocked_path_configured_binaries_have_real_version_and_filter_evidence(native_binaries, monkeypatch):
    ffmpeg, ffprobe = native_binaries
    expected = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True, timeout=10)
    token = expected.stdout.splitlines()[0].split()[2]
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", ffmpeg)
    monkeypatch.setenv("KINOCUT_FFPROBE_EXECUTABLE", ffprobe)
    monkeypatch.setenv("PATH", "")
    result = snapshot_capabilities(find_spec=lambda name: None)
    assert result["ffmpeg"] == {"available": True, "ffmpeg": True, "ffprobe": True, "version": token}
    assert all(result["filters"].values())
    assert _versions.ffmpeg_version() == token


def test_explicit_discovery_resolver_keeps_version_and_filters_bound_to_selected_binary(native_binaries):
    ffmpeg, ffprobe = native_binaries
    result = snapshot_capabilities(
        which=lambda name: ffmpeg if name == "ffmpeg" else ffprobe,
        find_spec=lambda name: None,
    )
    assert result["ffmpeg"]["version"] == _versions.ffmpeg_version(ffmpeg)
    assert all(result["filters"].values())


@pytest.mark.parametrize("flags", ["...", "TSC", "..", "TS"])
def test_filter_probe_accepts_legacy_and_current_flag_columns(monkeypatch, flags):
    identity = ("fixture", flags)
    monkeypatch.setattr(capabilities, "_binary_identity", lambda _: identity)
    monkeypatch.setattr(
        capabilities.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, f" {flags} loudnorm A->A Normalize\n", ""),
    )
    capabilities._probe_ffmpeg_filters.cache_clear()
    assert capabilities._probe_ffmpeg_filters("fixture", identity) == frozenset({"loudnorm"})
    capabilities._probe_ffmpeg_filters.cache_clear()


@pytest.mark.parametrize("line", ["T loudnorm A->A", "XXXX loudnorm A->A", "TS loudnorm invalid"])
def test_filter_probe_rejects_malformed_rows(monkeypatch, line):
    identity = ("fixture", line)
    monkeypatch.setattr(capabilities, "_binary_identity", lambda _: identity)
    monkeypatch.setattr(
        capabilities.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, line, ""),
    )
    capabilities._probe_ffmpeg_filters.cache_clear()
    assert capabilities._probe_ffmpeg_filters("fixture", identity) == frozenset()
    capabilities._probe_ffmpeg_filters.cache_clear()


def test_replacing_binary_with_preserved_mtime_invalidates_version_cache(native_binaries, tmp_path, monkeypatch):
    source = native_binaries[0]
    selected = tmp_path / "ffmpeg"
    shutil.copyfile(source, selected)
    selected.chmod(0o700)
    run = Mock(wraps=subprocess.run)
    monkeypatch.setattr(_versions.subprocess, "run", run)
    first = _versions.ffmpeg_version(str(selected))
    assert first
    assert _versions.ffmpeg_version(str(selected)) == first
    assert run.call_count == 1
    stat = selected.stat()
    replacement = tmp_path / "replacement"
    shutil.copyfile(source, replacement)
    replacement.chmod(0o700)
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(replacement, selected)
    assert _versions.ffmpeg_version(str(selected)) == first
    assert run.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("ffmpeg", 10),
        subprocess.CompletedProcess([], 1, "", "failed"),
        subprocess.CompletedProcess([], 0, "not a version", ""),
    ],
)
def test_failed_version_probes_retry_then_cache_success(native_binaries, monkeypatch, failure):
    selected = native_binaries[0]
    real_run = subprocess.run
    attempts = []

    def probe(*args, **kwargs):
        attempts.append(args[0])
        if len(attempts) == 1:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return real_run(*args, **kwargs)

    monkeypatch.setattr(_versions.subprocess, "run", probe)
    assert _versions.ffmpeg_version(selected) is None
    assert _versions._ffmpeg_version_cache is None
    assert _versions.ffmpeg_version(selected)
    assert _versions.ffmpeg_version(selected)
    assert len(attempts) == 2


def test_binary_mutation_during_version_probe_does_not_cache(native_binaries, tmp_path, monkeypatch):
    selected = tmp_path / "ffmpeg"
    shutil.copyfile(native_binaries[0], selected)
    selected.chmod(0o700)
    real_run = subprocess.run

    def mutate(*args, **kwargs):
        result = real_run(*args, **kwargs)
        stat = selected.stat()
        os.utime(selected, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        return result

    monkeypatch.setattr(_versions.subprocess, "run", mutate)
    assert _versions.ffmpeg_version(str(selected)) is None
    assert _versions._ffmpeg_version_cache is None
    monkeypatch.setattr(_versions.subprocess, "run", real_run)
    assert _versions.ffmpeg_version(str(selected))


def test_invalid_default_config_is_unavailable_without_fallback(native_binaries, monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", str(tmp_path / "missing"))
    assert _versions.ffmpeg_version() is None
    result = snapshot_capabilities(find_spec=lambda name: None)
    assert result["ffmpeg"]["ffmpeg"] is False
    assert result["ffmpeg"]["available"] is False
    assert result["ffmpeg"]["version"] is None
