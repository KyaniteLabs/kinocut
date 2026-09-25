from __future__ import annotations

import inspect
import json
import math
from types import SimpleNamespace

import pytest

from kinocut.models import EditResult
from kinocut.engine_audio_normalize import _measurement, normalize_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg


MEASUREMENT = json.dumps({"input_i": -20, "input_lra": 2, "input_tp": -3, "input_thresh": -30, "target_offset": 1})


def _mock_normalize(monkeypatch, tmp_path, *, duration: object = "2.0", audio: bool = True, stderr: str = MEASUREMENT):
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    calls: list[list[str]] = []
    streams = [{"codec_type": "audio" if audio else "video"}]
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"streams": streams, "format": {"duration": duration}},
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffmpeg",
        lambda command: calls.append(command) or SimpleNamespace(stderr=stderr),
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: EditResult(output_path=args[0])
    )
    return source, output, calls


def _filters(calls: list[list[str]]) -> list[str]:
    return [command[command.index("-af") + 1] for command in calls if "-af" in command]


def test_signature_adds_keyword_only_fade_without_moving_positional_api() -> None:
    params = list(inspect.signature(normalize_audio).parameters.values())
    assert [param.name for param in params[:4]] == ["input_path", "target_lufs", "lra", "output_path"]
    assert params[4].name == "true_peak_dbtp"
    assert params[5].name == "fade_seconds"
    assert params[5].kind is inspect.Parameter.KEYWORD_ONLY
    assert params[5].default == 0.01


def test_default_fades_precede_loudnorm_in_analysis_and_render(tmp_path, monkeypatch) -> None:
    source, output, calls = _mock_normalize(monkeypatch, tmp_path)
    normalize_audio(str(source), -14, 8, str(output), true_peak_dbtp=-2)

    assert len(calls) == 2
    for audio_filter in _filters(calls):
        assert audio_filter.startswith("afade=t=in:st=0:d=0.01,afade=t=out:st=1.99:d=0.01,loudnorm=")
    assert "print_format=json" in _filters(calls)[0]
    assert "measured_I=-20.0" in _filters(calls)[1]


def test_zero_fade_is_explicit_filter_bypass(tmp_path, monkeypatch) -> None:
    source, output, calls = _mock_normalize(monkeypatch, tmp_path)
    normalize_audio(str(source), output_path=str(output), fade_seconds=0)

    assert all(audio_filter.startswith("loudnorm=") for audio_filter in _filters(calls))
    assert all("afade" not in audio_filter for audio_filter in _filters(calls))


@pytest.mark.parametrize(
    ("duration", "fade", "expected"),
    [("4", 0.25, "st=3.75:d=0.25"), ("0.006", 0.01, "st=0.003:d=0.003")],
)
def test_custom_fade_and_half_duration_clamp(duration, fade, expected, tmp_path, monkeypatch) -> None:
    source, output, calls = _mock_normalize(monkeypatch, tmp_path, duration=duration)
    normalize_audio(str(source), output_path=str(output), fade_seconds=fade)

    assert expected in _filters(calls)[0]
    assert expected in _filters(calls)[1]


def test_no_audio_copy_has_no_fades(tmp_path, monkeypatch) -> None:
    source, output, calls = _mock_normalize(monkeypatch, tmp_path, duration=None, audio=False)
    normalize_audio(str(source), output_path=str(output))

    assert len(calls) == 1
    assert "-af" not in calls[0]
    assert calls[0][calls[0].index("-c:a") + 1] == "copy"


@pytest.mark.parametrize("value", [True, -0.01, 1.01, math.inf, math.nan, "0.1"])
def test_invalid_fade_values(value, tmp_path, monkeypatch) -> None:
    source, _, _ = _mock_normalize(monkeypatch, tmp_path)
    with pytest.raises(MCPVideoError, match="fade_seconds"):
        normalize_audio(str(source), fade_seconds=value)


@pytest.mark.parametrize("duration", [None, "bad", "nan", "inf", "0", "-1"])
def test_invalid_audio_duration_is_actionable(duration, tmp_path, monkeypatch) -> None:
    source, output, _ = _mock_normalize(monkeypatch, tmp_path, duration=duration)
    with pytest.raises(MCPVideoError, match="finite positive media duration") as excinfo:
        normalize_audio(str(source), output_path=str(output))
    assert excinfo.value.code == "invalid_media_duration"


def test_short_audio_one_pass_fallback_retains_clamped_fades(tmp_path, monkeypatch) -> None:
    stderr = json.dumps(
        {"input_i": "-inf", "input_lra": "0", "input_tp": "-inf", "input_thresh": "-70", "target_offset": "0"}
    )
    source, output, calls = _mock_normalize(monkeypatch, tmp_path, duration="0.006", stderr=stderr)
    normalize_audio(str(source), output_path=str(output))

    render_filter = _filters(calls)[1]
    assert render_filter.startswith("afade=t=in:st=0:d=0.003,afade=t=out:st=0.003:d=0.003,loudnorm=")
    assert "measured_I" not in render_filter


def _window_rms(samples: list[int], start: int, stop: int) -> float:
    window = samples[start:stop]
    return math.sqrt(sum(sample * sample for sample in window) / len(window))


def test_real_fixture_fades_boundaries_and_preserves_target_loudness(tmp_path) -> None:
    source, output, decoded = tmp_path / "tone.wav", tmp_path / "normalized.m4a", tmp_path / "decoded.s16le"
    _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", str(source)])
    normalize_audio(str(source), target_lufs=-14, output_path=str(output), fade_seconds=0.1)
    _run_ffmpeg(
        [
            "-i",
            str(output),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(decoded),
        ]
    )

    rate = 48_000
    raw = decoded.read_bytes()
    count = len(raw) // 2
    samples = [int.from_bytes(raw[index : index + 2], "little", signed=True) for index in range(0, len(raw), 2)]
    edge = int(rate * 0.05)
    middle = _window_rms(samples, count // 2 - edge // 2, count // 2 + edge // 2)
    assert _window_rms(samples, 0, edge) < middle * 0.7
    assert _window_rms(samples, count - edge, count) < middle * 0.7

    analysis = _run_ffmpeg(
        ["-i", str(output), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"]
    )
    assert _measurement(analysis.stderr)["measured_I"] == pytest.approx(-14, abs=1)
