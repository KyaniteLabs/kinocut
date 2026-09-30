"""Missing FFmpeg build components stay actionable across media surfaces."""

from __future__ import annotations

import json
import shutil

import pytest

from kinocut.errors import CodecError, InputFileError, ProcessingError, parse_ffmpeg_error


@pytest.mark.parametrize(
    "stderr,code",
    [
        ("Unknown encoder 'libx265'", "missing_encoder_libx265"),
        ("[vost#0:0 @ 0x1234] Unknown encoder 'libx264'", "missing_encoder_libx264"),
        ("[AVFilterGraph @ 0x1234] No such filter: 'drawtext'", "missing_filter_drawtext"),
        ("  UNKNOWN ENCODER 'LIBX265'\r\n", "missing_encoder_libx265"),
    ],
)
def test_missing_components_preserve_processing_catch_and_add_advisory(stderr, code):
    command = ["ffmpeg", "-i", "input.mp4", "-c:v", "libx265", "output.mp4"]
    error = parse_ffmpeg_error(stderr, command)
    assert isinstance(error, ProcessingError)
    assert error.command == " ".join(command)
    assert error.returncode == 1
    assert error.full_stderr == stderr
    payload = json.loads(json.dumps(error.to_dict()))
    assert payload["type"] == "dependency_error"
    assert payload["code"] == code
    assert payload["suggested_action"]["auto_fix"] is False
    assert "not changed" in payload["suggested_action"]["description"]
    if "LIBX265" in stderr:
        assert "'LIBX265'" in payload["suggested_action"]["description"]
        assert "exact component name" in payload["suggested_action"]["description"]
    assert command[4] == "libx265"


def test_banner_preserves_missing_encoder_before_terminal_error():
    stderr = "ffmpeg version 8.0\nbuilt with gcc\nUnknown encoder 'libx265'\nError opening output file output.mp4."
    assert parse_ffmpeg_error(stderr).code == "missing_encoder_libx265"


@pytest.mark.parametrize(
    "stderr",
    [
        "metadata title: Unknown encoder 'libx265'",
        "input.mp4: No such filter: 'drawtext'",
        "Unknown encoder 'libx265' was requested by a user",
        "Unknown encoder '../../libx265'",
        "No such filter: 'drawtext;movie=/etc/passwd'",
        "Unknown encoder '" + "x" * 65 + "'",
        "No such filter: 'd\u0440\u0430wtext'",  # Cyrillic letters are not component names.
        "Unknown encoder '\u212ainocut'",  # IGNORECASE alone accepts the Kelvin sign as K.
        "No such filter: '\u017fcale'",  # Long s must not pass an ASCII component contract.
        "Unknown encoder 'l\u0130bx265'",  # Dotted I must not normalize into a reason code.
        "Error initializing output stream: encoder cannot open device",
        "Unknown encoder ''",
    ],
)
def test_unconfirmed_or_unsafe_components_keep_generic_error(stderr):
    error = parse_ffmpeg_error(stderr)
    assert isinstance(error, ProcessingError)
    assert error.code == "ffmpeg_exit_1"
    assert "suggested_action" not in error.to_dict()


def test_existing_decoder_and_input_errors_keep_their_contracts():
    assert isinstance(parse_ffmpeg_error("Decoder vp9 not found: unsupported codec"), CodecError)
    assert isinstance(parse_ffmpeg_error("input.mp4: No such file or directory"), InputFileError)


def test_large_stderr_and_long_component_names_do_not_amplify_advisory():
    stderr = "metadata: " + "x" * 100_000 + "\nUnknown encoder 'libx265'\n" + "trace: " + "y" * 100_000
    error = parse_ffmpeg_error(stderr)
    assert error.code == "missing_encoder_libx265"
    assert len(json.dumps(error.to_dict())) < 1200
    assert len(error.suggested_action["description"]) < 300
    malformed = parse_ffmpeg_error("Unknown encoder '" + "x" * 100_000 + "'")
    assert malformed.code == "ffmpeg_exit_1"
    assert len(json.dumps(malformed.to_dict())) < 1000


def test_mcp_serializes_advisory_and_client_preserves_same_error(monkeypatch):
    from kinocut import Client
    from kinocut.server_app import _safe_tool

    error = parse_ffmpeg_error("Unknown encoder 'libx265'")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("kinocut.client.media._convert", fail)
    with pytest.raises(ProcessingError) as failure:
        Client().convert("input.mp4", output="output.mp4")
    assert failure.value is error
    result = _safe_tool(fail)()
    assert result == {"success": False, "error": error.to_dict()}
    assert result["error"]["suggested_action"]["auto_fix"] is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg required")
@pytest.mark.parametrize(
    "args,code",
    [
        (["-c:v", "kinocut_missing_encoder"], "missing_encoder_kinocut_missing_encoder"),
        (["-vf", "kinocut_missing_filter"], "missing_filter_kinocut_missing_filter"),
    ],
)
def test_real_unavailable_component_is_actionable_without_publishing(tmp_path, args, code):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    output = tmp_path / "output.mp4"
    with pytest.raises(ProcessingError) as failure:
        _run_ffmpeg(["-f", "lavfi", "-i", "color=black:s=16x16:d=0.1", *args, str(output)])
    assert failure.value.code == code
    assert failure.value.to_dict()["suggested_action"]["auto_fix"] is False
    assert not output.exists() or output.stat().st_size == 0
