from __future__ import annotations

import inspect
import json
import math
from types import SimpleNamespace

import pytest

from kinocut.engine_audio_normalize import _measurement, normalize_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json
from kinocut.models import EditResult
from kinocut.quality_guardrails import quality_check


def test_signature_preserves_positional_api() -> None:
    params = list(inspect.signature(normalize_audio).parameters.values())
    assert [p.name for p in params[:4]] == ["input_path", "target_lufs", "lra", "output_path"]
    assert params[4].name == "true_peak_dbtp" and params[4].kind is inspect.Parameter.KEYWORD_ONLY
    assert params[4].default == -1.5


def test_measurement_rejects_bad_json() -> None:
    for text in ["", "{}", '{"input_i": "nan", "input_lra": 1, "input_tp": 1, "input_thresh": 1, "target_offset": 1}']:
        with pytest.raises(MCPVideoError):
            _measurement(text)


def test_measurement_reads_final_json() -> None:
    data = {"input_i": -20, "input_lra": 2, "input_tp": -3, "input_thresh": -30, "target_offset": 1}
    assert _measurement("noise\n" + json.dumps(data))["measured_I"] == -20


@pytest.mark.parametrize(
    "name,value",
    [
        ("target_lufs", True),
        ("target_lufs", math.inf),
        ("target_lufs", 10**1000),
        ("lra", -1),
        ("lra", 0),
        ("true_peak_dbtp", 1),
        ("true_peak_dbtp", -10),
    ],
)
def test_numeric_validation(name: str, value: object, tmp_path, monkeypatch) -> None:
    source = tmp_path / "in.wav"
    source.write_bytes(b"x")
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    with pytest.raises(MCPVideoError, match=name):
        normalize_audio(str(source), **{name: value})


def test_two_pass_commands_and_measured_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._validate_normalized_output",
        lambda *_args: {"format": {"format_name": "wav"}, "streams": []},
    )
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    calls = []
    analysis = SimpleNamespace(
        stderr=json.dumps({"input_i": -20, "input_lra": 2, "input_tp": -3, "input_thresh": -30, "target_offset": 1})
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio", "duration": "1.0"}]},
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._run_ffmpeg", lambda command: calls.append(command) or analysis)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: EditResult(output_path=args[0])
    )
    result = normalize_audio(str(source), -14, 8, str(output), true_peak_dbtp=-2)
    assert result.output_path == str(output)
    assert result.measured_input.model_dump() == {"I": -20.0, "LRA": 2.0, "TP": -3.0}
    assert result.measured_output is None
    assert len(calls) == 2 and all(isinstance(command, list) for command in calls)
    # Analysis measures audio only; the render still retains the original video stream.
    assert "-vn" in calls[0] and "-vn" in calls[1]
    assert calls[1][calls[1].index("-c:a") + 1] == "pcm_s16le"
    assert "measured_I=-20.0" in calls[1][calls[1].index("-af") + 1]
    assert "TP=-2.0" in calls[1][calls[1].index("-af") + 1]
    assert "linear=true" in calls[1][calls[1].index("-af") + 1]
    # loudnorm upsamples to 192 kHz; the output goes back to 48 kHz when the source rate is unknown.
    assert calls[1][calls[1].index("-af") + 1].endswith(",aresample=48000,asetpts=N/SR/TB,apad")
    # -3 dBTP + 6 dB of gain = +3 dBTP > -2: loudnorm cannot stay linear, and says so.
    assert len(result.warnings) == 1 and "dynamic mode" in result.warnings[0]


def test_linear_gain_within_ceiling_has_no_warning_and_keeps_source_rate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._validate_normalized_output",
        lambda *_args: {"format": {"format_name": "wav"}, "streams": []},
    )
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    calls = []
    analysis = SimpleNamespace(
        stderr=json.dumps({"input_i": -20, "input_lra": 2, "input_tp": -12, "input_thresh": -30, "target_offset": 1})
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {
            "format": {"duration": "1.0"},
            "streams": [{"codec_type": "audio", "sample_rate": "44100", "duration": "1.0"}],
        },
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._run_ffmpeg", lambda command: calls.append(command) or analysis)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: EditResult(output_path=args[0])
    )
    result = normalize_audio(str(source), -16, 11, str(output), true_peak_dbtp=-2)
    assert result.warnings == []
    assert calls[1][calls[1].index("-af") + 1].endswith(
        "linear=true:print_format=json,aresample=44100,asetpts=N/SR/TB,apad"
    )


def test_real_output_keeps_the_source_sample_rate(sample_video: str, tmp_path) -> None:
    output = tmp_path / "normalized.mp4"
    result = normalize_audio(sample_video, target_lufs=-16.0, output_path=str(output))
    rates = {
        stream["sample_rate"]
        for path in (sample_video, result.output_path)
        for stream in _run_ffprobe_json(path)["streams"]
        if stream.get("codec_type") == "audio"
    }
    assert len(rates) == 1, rates


def test_no_audio_input_uses_stream_copy_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._validate_normalized_output",
        lambda *_args: {"format": {"format_name": "wav"}, "streams": []},
    )
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
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: EditResult(output_path=args[0])
    )

    copied = normalize_audio(str(source), output_path=str(output))
    assert copied.output_path == str(output)
    assert copied.measured_input is None and copied.measured_output is None
    assert len(calls) == 1
    assert "-af" not in calls[0]


def test_short_audio_uses_one_pass_fallback_for_infinite_measurement(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._validate_normalized_output",
        lambda *_args: {"format": {"format_name": "wav"}, "streams": []},
    )
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
        lambda _path: {"format": {"duration": "0.1"}, "streams": [{"codec_type": "audio", "duration": "0.1"}]},
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffmpeg",
        lambda command: calls.append(command) or analysis,
    )
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result", lambda *args, **kwargs: EditResult(output_path=args[0])
    )

    result = normalize_audio(str(source), output_path=str(output))

    assert result.measured_input is None and result.measured_output is None
    assert len(calls) == 2
    assert all("TP=-1.5" in command[command.index("-af") + 1] for command in calls)
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
    assert result.measured_input is not None and result.measured_output is not None
    assert math.isfinite(result.measured_input.I)
    assert math.isfinite(result.measured_input.LRA)
    assert math.isfinite(result.measured_input.TP)
    assert pytest.approx(-14.0, abs=1.0) == result.measured_output.I
    assert math.isfinite(result.measured_output.TP)


def test_real_default_margin_clears_production_audio_gate(tmp_path) -> None:
    source = tmp_path / "paired-input.mp4"
    old_output = tmp_path / "explicit-old.mp4"
    default_output = tmp_path / "omitted-default.mp4"
    tone = "aevalsrc=0.95*sin(2*PI*997*t)*between(mod(t\\,1.0)\\,0\\,0.05):s=48000:d=6"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=6",
            "-f",
            "lavfi",
            "-i",
            tone,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-shortest",
            str(source),
        ]
    )
    normalize_audio(str(source), target_lufs=-14.0, output_path=str(old_output), true_peak_dbtp=-1.0)
    normalize_audio(str(source), target_lufs=-14.0, output_path=str(default_output))

    measured = []
    audio_rows = []
    for output in (old_output, default_output):
        _run_ffmpeg(["-v", "error", "-i", str(output), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
        result = _run_ffmpeg(
            ["-i", str(output), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"]
        )
        measured.append(_measurement(result.stderr))
        report = quality_check(str(output))
        audio_rows.append(next(row for row in report["checks"] if row["name"] == "audio_levels"))

    assert all(item["measured_I"] == pytest.approx(-14.0, abs=1.0) for item in measured)
    assert measured[0]["measured_TP"] > -1.0
    assert measured[1]["measured_TP"] <= -1.0
    assert audio_rows[0]["passed"] is False
    assert audio_rows[1]["passed"] is True


LOUDNESS_SNAPSHOT = {
    "measured_input": {"I": -20.0, "LRA": 2.0, "TP": -12.0},
    "measured_output": {"I": -16.0, "TP": -8.0},
}


def test_measured_loudness_snapshot_reaches_cli_and_mcp(tmp_path, monkeypatch, capsys) -> None:
    """Freeze the additive before/after readings on the result, CLI, and MCP payload."""
    from io import StringIO

    from rich.console import Console

    from kinocut.cli.common import output_json
    from kinocut.cli.formatting import _format_edit_text
    from kinocut.engine_audio_normalize_output import NormalizedAudioResult
    from kinocut.server_app import _result

    import kinocut.cli.formatting as formatting

    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._validate_normalized_output",
        lambda *_args: {
            "format": {"format_name": "wav"},
            "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
        },
    )
    source, output = tmp_path / "in.wav", tmp_path / "out.wav"
    source.write_bytes(b"x")
    analysis = {
        "input_i": -20,
        "input_lra": 2,
        "input_tp": -12,
        "input_thresh": -30,
        "target_offset": 0.5,
        "output_i": -99,
        "output_tp": -50,
    }
    rendered = {
        "input_i": -19,
        "input_lra": 3,
        "input_tp": -11,
        "input_thresh": -29,
        "target_offset": 0.25,
        "output_i": -16,
        "output_tp": -8,
        "normalization_type": "linear",
    }
    responses = [json.dumps(analysis), json.dumps(rendered)]
    calls = []

    def runner(command):
        calls.append(command)
        return SimpleNamespace(stderr=responses.pop(0))

    monkeypatch.setattr("kinocut.engine_audio_normalize._require_filter", lambda *args: None)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._run_ffprobe_json",
        lambda _path: {"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio", "duration": "1.0"}]},
    )
    monkeypatch.setattr("kinocut.engine_audio_normalize._run_ffmpeg", runner)
    monkeypatch.setattr(
        "kinocut.engine_audio_normalize._build_edit_result",
        lambda *args, **kwargs: EditResult(output_path=args[0], operation=args[1]),
    )

    result = normalize_audio(str(source), output_path=str(output))

    assert isinstance(result, NormalizedAudioResult)
    assert {key: result.model_dump()[key] for key in LOUDNESS_SNAPSHOT} == LOUDNESS_SNAPSHOT
    assert "print_format=json" in calls[1][calls[1].index("-af") + 1]
    compatible = NormalizedAudioResult(output_path=str(output), audio_codec="pcm_s16le")
    assert compatible.measured_input is None and compatible.measured_output is None

    payload = _result(result)
    assert {key: payload[key] for key in LOUDNESS_SNAPSHOT} == LOUDNESS_SNAPSHOT
    assert payload["success"] is True and payload["operation"] == "normalize_audio"
    assert payload["audio_codec"] == "pcm_s16le"

    output_json(result)
    cli_json = json.loads(capsys.readouterr().out)
    assert {key: cli_json[key] for key in LOUDNESS_SNAPSHOT} == LOUDNESS_SNAPSHOT

    text_console = Console(file=StringIO(), record=True, force_terminal=True, width=120, color_system=None)
    monkeypatch.setattr(formatting, "console", text_console)
    _format_edit_text(result)
    text = text_console.export_text()
    assert "Input loudness: I -20.00 LUFS, LRA 2.00 LU, TP -12.00 dBTP" in text
    assert "Output loudness: I -16.00 LUFS, TP -8.00 dBTP" in text

    plain = Console(file=StringIO(), record=True, force_terminal=True, width=120, color_system=None)
    monkeypatch.setattr(formatting, "console", plain)
    _format_edit_text({"operation": "trim", "output_path": str(output)})
    plain_text = plain.export_text()
    assert "Input loudness" not in plain_text
    assert "Output loudness" not in plain_text
