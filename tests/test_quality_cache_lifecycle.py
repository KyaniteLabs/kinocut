"""Measurement caches must follow source replacement and transient probe recovery."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from kinocut import quality_guardrails
from kinocut.quality_guardrails import VisualQualityGuardrails


@pytest.fixture
def source_metadata(monkeypatch):
    probe = Mock(return_value={"streams": [{"codec_type": "video", "pix_fmt": "yuv420p"}]})
    monkeypatch.setattr("kinocut.quality_source._run_ffprobe_json", probe)
    return probe


def _probe_result(value=128):
    return subprocess.CompletedProcess(
        [], 0, json.dumps({"frames": [{"tags": {"lavfi.signalstats.YAVG": str(value)}}]}), ""
    )


def test_unchanged_source_reuses_measurement_but_changed_window_reanalyzes(tmp_path, monkeypatch, source_metadata):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fixture")
    probe = Mock(return_value=_probe_result())
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    guardrails = VisualQualityGuardrails()
    assert guardrails.check_brightness(str(video)).passed
    assert guardrails.check_brightness(str(video)).passed
    assert probe.call_count == 1
    assert source_metadata.call_count == 1
    assert guardrails._has_audio_stream(str(video)) is False
    assert source_metadata.call_count == 1
    guardrails.max_analyze_seconds = 1.0
    assert guardrails.check_brightness(str(video)).passed
    assert probe.call_count == 2
    assert source_metadata.call_count == 2


def test_same_size_source_replacement_with_preserved_mtime_reanalyzes(tmp_path, monkeypatch, source_metadata):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"old")
    old_stat = video.stat()
    probe = Mock(side_effect=[_probe_result(128), _probe_result(235)])
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    guardrails = VisualQualityGuardrails()
    assert guardrails.check_brightness(str(video)).passed
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"new")
    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    replacement.replace(video)
    assert not guardrails.check_brightness(str(video)).passed
    assert probe.call_count == 2
    assert source_metadata.call_count == 2


def test_source_mutation_during_probe_is_not_cached(tmp_path, monkeypatch, source_metadata):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"before")

    def mutate_once(*args, **kwargs):
        if video.read_bytes() == b"before":
            video.write_bytes(b"after mutation")
            return _probe_result(16)
        return _probe_result(128)

    probe = Mock(side_effect=mutate_once)
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    guardrails = VisualQualityGuardrails()
    assert not guardrails.check_brightness(str(video)).passed
    assert guardrails.check_brightness(str(video)).passed
    assert probe.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CompletedProcess([], 1, "", "probe unavailable"),
        subprocess.CompletedProcess([], 0, "not JSON", ""),
        subprocess.CompletedProcess([], 0, '{"frames": []}', ""),
        subprocess.TimeoutExpired("ffprobe", 1),
    ],
)
def test_failed_probe_retries_on_next_request(tmp_path, monkeypatch, failure, source_metadata):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fixture")
    probe = Mock(side_effect=[failure, _probe_result()])
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    guardrails = VisualQualityGuardrails()
    assert guardrails._get_all_signalstats(str(video)) == {}
    assert guardrails.check_brightness(str(video)).passed
    assert probe.call_count == 2


def test_signalstats_cache_evicts_least_recent_measurement(tmp_path, monkeypatch, source_metadata):
    monkeypatch.setattr("kinocut.quality_source.QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(quality_guardrails, "QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES", 2)
    probe = Mock(return_value=_probe_result())
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    videos = [tmp_path / f"clip{index}.mp4" for index in range(3)]
    for video in videos:
        video.write_bytes(b"fixture")
    guardrails = VisualQualityGuardrails()
    for index in (0, 1, 0, 2, 0):
        assert guardrails.check_brightness(str(videos[index])).passed
    assert probe.call_count == 3
    assert guardrails.check_brightness(str(videos[1])).passed
    assert probe.call_count == 4
    assert len(guardrails._signalstats_cache) == 2
    assert len(guardrails._quality_source_cache) == 2


def test_unstatable_mock_source_still_analyzes_without_caching(tmp_path, monkeypatch, source_metadata):
    probe = Mock(return_value=_probe_result())
    monkeypatch.setattr(quality_guardrails.subprocess, "run", probe)
    guardrails = VisualQualityGuardrails()
    for _ in range(2):
        assert guardrails.check_brightness(str(tmp_path / "not-present.mp4")).passed
    assert probe.call_count == 2
    assert not guardrails._signalstats_cache


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_real_video_replacement_updates_brightness(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    guardrails = VisualQualityGuardrails()
    values = []
    for color in ("black", "white"):
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=160x120:r=25:d=0.52",
                "-c:v",
                "libx264",
                str(video),
            ],
            check=True,
            timeout=30,
        )
        values.append(guardrails.check_brightness(str(video)).details["y_avg"])
    assert values == pytest.approx([16.0, 235.0])
