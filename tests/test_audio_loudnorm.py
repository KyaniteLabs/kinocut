from __future__ import annotations

import inspect
import json
import math
from types import SimpleNamespace

import pytest

from kinocut.engine_audio_normalize import _measurement, normalize_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg


def test_signature_preserves_positional_api() -> None:
    params = list(inspect.signature(normalize_audio).parameters.values())
    assert [p.name for p in params[:4]] == ["input_path", "target_lufs", "lra", "output_path"]
    assert params[4].name == "true_peak_dbtp" and params[4].kind is inspect.Parameter.KEYWORD_ONLY


def test_measurement_rejects_bad_json() -> None:
    for text in ["", "{}", '{"input_i": "nan", "input_lra": 1, "input_tp": 1, "input_thresh": 1, "target_offset": 1}']:
        with pytest.raises(MCPVideoError):
            _measurement(text)


def test_measurement_reads_final_json() -> None:
    data = {"input_i": -20, "input_lra": 2, "input_tp": -3, "input_thresh": -30, "target_offset": 1}
    assert _measurement("noise\n" + json.dumps(data))["measured_I"] == -20


@pytest.mark.parametrize(
    "name,value", [("target_lufs", True), ("target_lufs", math.inf), ("lra", -1), ("true_peak_dbtp", 1)]
)
def test_numeric_validation(name: str, value: object, tmp_path, monkeypatch) -> None:
    source = tmp_path / "in.wav"
    source.write_bytes(b"x")
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    with pytest.raises(MCPVideoError, match=name):
        normalize_audio(str(source), **{name: value})


def test_two_pass_commands_and_measured_values(tmp_path, monkeypatch) -> None:
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    calls = []
    analysis = SimpleNamespace(
        stderr=json.dumps({"input_i": -20, "input_lra": 2, "input_tp": -3, "input_thresh": -30, "target_offset": 1})
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"streams": [{"codec_type": "audio"}]},
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._run_ffmpeg", lambda command: calls.append(command) or analysis)
    monkeypatch.setattr("kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: args[0])
    assert normalize_audio(str(source), -14, 8, str(output), true_peak_dbtp=-2) == str(output)
    assert len(calls) == 2 and all(isinstance(command, list) for command in calls)
    assert "measured_I=-20.0" in calls[1][calls[1].index("-af") + 1]
    assert "TP=-2.0" in calls[1][calls[1].index("-af") + 1]
    assert "linear=true" in calls[1][calls[1].index("-af") + 1]


def test_no_audio_input_uses_stream_copy_fallback(tmp_path, monkeypatch) -> None:
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source.write_bytes(b"x")
    calls = []
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"streams": [{"codec_type": "video"}]},
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffmpeg",
        lambda command: calls.append(command) or SimpleNamespace(stderr=""),
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: args[0])

    assert normalize_audio(str(source), output_path=str(output)) == str(output)
    assert len(calls) == 1
    assert "-af" not in calls[0]


def test_short_audio_uses_one_pass_fallback_for_infinite_measurement(tmp_path, monkeypatch) -> None:
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    calls = []
    analysis = SimpleNamespace(
        stderr=json.dumps(
            {
                "input_i": "-inf",
                "input_lra": "0.0",
                "input_tp": "-inf",
                "input_thresh": "-70.0",
                "target_offset": "0.0",
            }
        )
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"streams": [{"codec_type": "audio"}]},
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffmpeg",
        lambda command: calls.append(command) or analysis,
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: args[0])

    normalize_audio(str(source), output_path=str(output))

    assert len(calls) == 2
    assert "measured_I" not in calls[1][calls[1].index("-af") + 1]


def test_real_two_pass_output_meets_loudness_and_peak_targets(sample_video: str, tmp_path) -> None:
    output = tmp_path / "normalized.mp4"

    result = normalize_audio(
        sample_video,
        target_lufs=-14.0,
        output_path=str(output),
        true_peak_dbtp=-2.0,
    )
    analysis = _run_ffmpeg(
        [
            "-i",
            result.output_path,
            "-af",
            "loudnorm=I=-14:TP=-2:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    measured = _measurement(analysis.stderr)

    assert measured["measured_I"] == pytest.approx(-14.0, abs=1.0)
    assert measured["measured_TP"] <= -1.5
