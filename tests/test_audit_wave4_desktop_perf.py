import subprocess
import sys
import tracemalloc
from types import SimpleNamespace
from array import array

import pytest

from kinocut.audio_sync.onsets import Onset, _envelope_onsets, _pcm_frames, pocket_lock


def test_describe_does_not_import_unrelated_tools():
    program = """
import sys
import kinocut.server
from kinocut.server_tools_families import describe_operation
before = set(sys.modules)
result = describe_operation('video_ai_remove_silence')
assert result['success']
assert 'kinocut.server_tools_hyperframes' not in set(sys.modules) - before
"""
    subprocess.run([sys.executable, "-c", program], check=True, timeout=30)


def test_pcm_frames_uses_compact_storage():
    raw = bytes([128]) * (1024 * 1024)
    tracemalloc.start()
    try:
        result = _pcm_frames(raw, 1, 1)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert isinstance(result, array)
    assert len(result) == len(raw)
    assert peak < 12 * 1024 * 1024


def test_audio_decode_enforces_offline_protocols(monkeypatch, tmp_path):
    from kinocut.audio_sync import onsets

    commands = []
    monkeypatch.setenv("KINOCUT_OFFLINE", "1")
    monkeypatch.setattr(onsets, "record_operation_input", lambda path: None)
    monkeypatch.setattr(onsets, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        onsets,
        "run_bounded",
        lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0, stdout=b""),
    )
    onsets._read_mono(tmp_path / "input.mp3", 48000)
    assert commands[0][commands[0].index("-i") - 2 : commands[0].index("-i")] == ["-protocol_whitelist", "file,pipe"]


def test_unsupported_pcm_width_is_value_error():
    with pytest.raises(ValueError, match="width"):
        _pcm_frames(b"", 5, 1)


def test_constant_noise_has_no_initial_onset():
    assert _envelope_onsets([0.003] * 100, "hat", 0.001) == []


def test_pocket_lock_rounds_half_up():
    events, _ = pocket_lock([{"time_s": 0.025}], [Onset(0.025, "hat", 1.0, 1.0)], fine_grid_step_ms=10)
    assert events[0]["time_s"] == 0.03
