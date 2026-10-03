"""Existing operator routes share media controls and preserve engine behavior."""

import asyncio
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from kinocut import Client, engine_convert, server_tools_advanced, server_tools_basic
from kinocut.cli.handlers_advanced import handle_advanced_commands
from kinocut.cli.handlers_core import handle_initial_command
from kinocut.cli.handlers_media import handle_media_commands
from kinocut.cli.parser import build_parser
from kinocut.defaults import DEFAULT_LRA_TARGET
from kinocut.engine_audio_normalize import normalize_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json
from kinocut.models import EditResult, QUALITY_PRESETS
from kinocut.models import ThumbnailResult
from kinocut.server import mcp
from kinocut.validation import VALID_FORMATS


@pytest.fixture
def parity_source(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")
    source = tmp_path / "source.mp4"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x96:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    return source


@pytest.mark.parametrize("format", sorted(VALID_FORMATS))
def test_cli_convert_accepts_every_engine_format(format):
    args = build_parser().parse_args(["convert", "source.mp4", "--format", format])
    assert args.fmt == format
    assert args.two_pass is False and args.target_bitrate is None


@pytest.mark.parametrize("field", ["start", "duration", "end"])
def test_mcp_trim_accepts_numeric_seconds_and_rejects_booleans(field):
    model = mcp._tool_manager._tools["video_trim"].fn_metadata.arg_model
    for value in [1, 1.25, "00:00:01.250"]:
        parsed = model.model_validate({"input_path": "source.mp4", field: value})
        assert getattr(parsed, field) == value
    with pytest.raises(ValidationError):
        model.model_validate({"input_path": "source.mp4", field: True})
    result = server_tools_basic.video_trim("source.mp4", **{field: True})
    assert result["error"]["type"] == "validation_error"


def test_cli_trim_and_conversion_forward_new_controls(monkeypatch, capsys):
    trim = Mock(return_value=EditResult(output_path="trimmed.mp4"))
    convert = Mock(return_value=EditResult(output_path="converted.mp4"))
    monkeypatch.setattr("kinocut.engine.trim", trim)
    monkeypatch.setattr("kinocut.engine.convert", convert)
    parser = build_parser()
    args = parser.parse_args(["trim", "source.mp4", "--start", "0.25", "--duration", "0.5", "--accurate"])
    assert handle_initial_command(args, use_json=True)
    assert trim.call_args.kwargs["accurate"] is True
    args = parser.parse_args(["convert", "source.mp4", "--two-pass", "--target-bitrate", "256"])
    assert handle_initial_command(args, use_json=True)
    assert convert.call_args.kwargs["two_pass"] is True
    assert convert.call_args.kwargs["target_bitrate"] == 256
    capsys.readouterr()


def test_mcp_conversion_forwards_bitrate_and_progress(parity_source, monkeypatch):
    convert = Mock(return_value=EditResult(output_path="converted.mp4"))
    monkeypatch.setattr(server_tools_basic, "convert", convert)
    result = asyncio.run(server_tools_basic.video_convert(str(parity_source), two_pass=True, target_bitrate=256))
    assert result["output_path"] == "converted.mp4"
    assert convert.call_args.kwargs["two_pass"] is True
    assert convert.call_args.kwargs["target_bitrate"] == 256
    assert "on_progress" in convert.call_args.kwargs


@pytest.mark.parametrize("surface", ["client", "mcp", "cli"])
@pytest.mark.parametrize("explicit", [False, True])
def test_normalization_controls_and_engine_defaults_match(surface, explicit, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.mp4"
    source.touch()
    engine = Mock(return_value=EditResult(output_path="normalized.mp4"))
    controls = {"lra": 7.0, "true_peak_dbtp": -2.0, "fade_seconds": 0.0} if explicit else {}
    if surface == "client":
        monkeypatch.setattr("kinocut.client.media._normalize_audio", engine)
        Client().normalize_audio(str(source), **controls)
    elif surface == "mcp":
        monkeypatch.setattr(server_tools_advanced, "normalize_audio", engine)
        server_tools_advanced.video_normalize_audio(str(source), **controls)
    else:
        monkeypatch.setattr("kinocut.engine.normalize_audio", engine)
        argv = ["normalize-audio", str(source)]
        if explicit:
            argv += ["--lra", "7", "--true-peak-dbtp", "-2", "--fade-seconds", "0"]
        assert handle_media_commands(build_parser().parse_args(argv), use_json=True)
        capsys.readouterr()
    forwarded = engine.call_args.kwargs
    defaults = inspect.signature(normalize_audio).parameters
    for name in ["target_lufs", "lra", "true_peak_dbtp", "fade_seconds"]:
        assert forwarded.get(name, defaults[name].default) == controls.get(name, defaults[name].default)
    assert defaults["lra"].default == DEFAULT_LRA_TARGET


def test_cli_hls_forwards_options_and_preserves_shared_defaults(monkeypatch, capsys):
    engine = Mock(return_value=EditResult(output_path="master.m3u8"))
    monkeypatch.setattr("kinocut.engine.hls_segment", engine)
    parser = build_parser()
    assert handle_media_commands(parser.parse_args(["hls-segment", "source.mp4"]), use_json=True)
    engine.assert_called_once_with("source.mp4", output_dir=None)
    args = parser.parse_args(
        [
            "hls-segment",
            "source.mp4",
            "--output-dir",
            "package",
            "--segment-duration",
            "2",
            "--playlist-name",
            "master.m3u8",
            "--qualities",
            "low",
            "medium",
        ]
    )
    assert handle_media_commands(args, use_json=True)
    engine.assert_called_with(
        "source.mp4",
        output_dir="package",
        segment_duration=2,
        playlist_name="master.m3u8",
        qualities=["low", "medium"],
    )
    capsys.readouterr()


def test_cli_checkpoint_forwards_intentionally_silent_choice(monkeypatch, capsys):
    engine = Mock(return_value={"success": True})
    monkeypatch.setattr("kinocut.server_tools_ai.video_release_checkpoint", engine)
    args = build_parser().parse_args(["release-checkpoint", "silent.mp4", "--no-require-audio"])
    assert handle_advanced_commands(args, use_json=True)
    assert engine.call_args.kwargs["require_audio"] is False
    capsys.readouterr()


@pytest.mark.parametrize("format", ["mp4", "mov", "webm", "hevc", "av1"])
def test_single_pass_codecs_use_requested_bitrate_without_conflicting_crf(format, monkeypatch):
    run = Mock()
    monkeypatch.setattr(engine_convert, "_run_ffmpeg_with_progress", run)
    getattr(engine_convert, f"_convert_{format}")("source.mp4", "output", QUALITY_PRESETS["high"], 1, None, 256)
    cmd = run.call_args.args[0]
    assert cmd[cmd.index("-b:v") + 1] == "256k"
    assert "-crf" not in cmd


@pytest.mark.parametrize("bitrate", [True, False, 0, -1, 1.5, "256", float("inf"), 10**1000])
def test_convert_rejects_invalid_bitrate_before_media_probe(bitrate, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    probe = Mock()
    monkeypatch.setattr(engine_convert, "probe", probe)
    with pytest.raises(MCPVideoError):
        engine_convert.convert(str(source), target_bitrate=bitrate)
    probe.assert_not_called()


@pytest.mark.parametrize("format", ["gif", "prores"])
def test_convert_rejects_bitrate_for_fixed_quality_formats(format, tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    with pytest.raises(MCPVideoError) as error:
        engine_convert.convert(str(source), format=format, target_bitrate=256)
    assert error.value.code == "target_bitrate_unsupported_format"


def test_real_numeric_trim_and_single_pass_bitrate_keep_source(parity_source, tmp_path, monkeypatch):
    digest = hashlib.sha256(parity_source.read_bytes()).hexdigest()
    trimmed = server_tools_basic.video_trim(
        str(parity_source),
        start=0.25,
        duration=0.5,
        output_path=str(tmp_path / "trimmed.mp4"),
        accurate=True,
    )
    assert trimmed["success"] is True
    assert trimmed["duration"] == pytest.approx(0.5, abs=0.08)
    run = Mock(wraps=engine_convert._run_ffmpeg_with_progress)
    monkeypatch.setattr(engine_convert, "_run_ffmpeg_with_progress", run)
    output = engine_convert.convert(str(parity_source), output_path=str(tmp_path / "bitrate.mp4"), target_bitrate=128)
    stream = next(s for s in _run_ffprobe_json(output.output_path)["streams"] if s["codec_type"] == "video")
    assert stream["codec_name"] == "h264"
    assert int(stream["bit_rate"]) > 0
    assert run.call_args.args[0][run.call_args.args[0].index("-b:v") + 1] == "128k"
    higher = engine_convert.convert(
        str(parity_source), output_path=str(tmp_path / "higher-bitrate.mp4"), target_bitrate=1024
    )
    higher_stream = next(s for s in _run_ffprobe_json(higher.output_path)["streams"] if s["codec_type"] == "video")
    assert int(higher_stream["bit_rate"]) > int(stream["bit_rate"])
    assert hashlib.sha256(parity_source.read_bytes()).hexdigest() == digest


def test_real_cli_two_pass_bitrate(parity_source, tmp_path):
    output = tmp_path / "two-pass.mp4"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "convert",
            str(parity_source),
            "--two-pass",
            "--target-bitrate",
            "128",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["success"] is True
    video = next(s for s in _run_ffprobe_json(str(output))["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264" and int(video["bit_rate"]) > 0


def test_real_cli_accurate_trim_and_hls_package(parity_source, tmp_path):
    commands = [
        [
            "trim",
            str(parity_source),
            "--start",
            "0.25",
            "--duration",
            "0.5",
            "--accurate",
            "-o",
            str(tmp_path / "trim.mp4"),
        ],
        [
            "hls-segment",
            str(parity_source),
            "-o",
            str(tmp_path / "hls"),
            "--qualities",
            "low",
            "--segment-duration",
            "1",
        ],
    ]
    for args in commands:
        result = subprocess.run(
            [sys.executable, "-m", "kinocut", "--format", "json", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["success"] is True and Path(receipt["output_path"]).is_file()
        if args[0] == "hls-segment":
            assert "#EXTM3U" in Path(receipt["output_path"]).read_text()
            assert list((tmp_path / "hls" / "low").glob("*.ts"))


def test_real_normalization_controls_are_available_on_all_surfaces(parity_source, tmp_path):
    controls = {"lra": 7.0, "true_peak_dbtp": -2.0, "fade_seconds": 0.0}
    outputs = [tmp_path / f"{name}.m4a" for name in ["client", "mcp", "cli"]]
    Client().normalize_audio(str(parity_source), output=str(outputs[0]), **controls)
    result = server_tools_advanced.video_normalize_audio(str(parity_source), output_path=str(outputs[1]), **controls)
    assert result["success"] is True
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "normalize-audio",
            str(parity_source),
            "--lra",
            "7",
            "--true-peak-dbtp",
            "-2",
            "--fade-seconds",
            "0",
            "-o",
            str(outputs[2]),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert cli.returncode == 0, cli.stderr
    for output in outputs:
        stream = next(s for s in _run_ffprobe_json(str(output))["streams"] if s["codec_type"] == "audio")
        assert stream["codec_name"] == "aac"
        assert float(stream["duration"]) == pytest.approx(1.0, abs=0.03)


def test_real_cli_checkpoint_accepts_intentionally_silent_film(parity_source, tmp_path):
    silent = tmp_path / "silent.mp4"
    _run_ffmpeg(["-i", str(parity_source), "-c:v", "copy", "-an", str(silent)])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "release-checkpoint",
            str(silent),
            "--no-require-audio",
            "--min-score",
            "0",
            "--frame-count",
            "2",
            "-o",
            str(tmp_path / "review"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["quality"]["all_passed"] is True
    assert receipt["review_required"] is True
    assert Path(receipt["thumbnail"]).is_file()


@pytest.mark.parametrize("timestamp", [None, 0.0, 0.25])
def test_mcp_frame_sampling_matches_client_engine_and_preserves_explicit_zero(timestamp, monkeypatch):
    from kinocut.server_tools_guardrails import video_extract_frame

    selected = 0.1 if timestamp is None else timestamp
    frame = ThumbnailResult(frame_path="frame.jpg", timestamp=selected)
    thumbnail = Mock(return_value=frame)
    monkeypatch.setattr("kinocut.engine_thumbnail.thumbnail", thumbnail)
    result = video_extract_frame("source.mp4", timestamp=timestamp, output_path="frame.jpg")
    thumbnail.assert_called_once_with("source.mp4", timestamp=timestamp, output_path="frame.jpg")
    assert result == {"success": True, "output_path": "frame.jpg", "timestamp": selected}


def test_real_mcp_frame_extraction_shares_automatic_sampling_with_client(parity_source, tmp_path, monkeypatch):
    from kinocut.server_tools_guardrails import video_extract_frame

    monkeypatch.setattr("kinocut.aesthetic.smart_thumbnail.find_best_thumbnail_timestamp", lambda _: 0.25)
    automatic = video_extract_frame(str(parity_source), output_path=str(tmp_path / "mcp.jpg"))
    client = Client().extract_frame(str(parity_source), output=str(tmp_path / "client.jpg"))
    first = video_extract_frame(str(parity_source), timestamp=0.0, output_path=str(tmp_path / "first.jpg"))
    assert automatic["timestamp"] == client.timestamp == 0.25
    assert first["timestamp"] == 0.0
    assert Path(automatic["output_path"]).read_bytes() == Path(client.output_path).read_bytes()
    assert Path(first["output_path"]).is_file()
