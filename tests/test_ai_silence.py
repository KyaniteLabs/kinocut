"""Focused correctness and artifact-validity tests for silence removal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from kinocut.ai_engine import silence
from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT, DEFAULT_SILENCE_DURATION_TOLERANCE_SECONDS
from kinocut.errors import MCPVideoError, ProcessingError


def _run_media(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=DEFAULT_FFMPEG_TIMEOUT,
    )


def _audio_source(kind: str, duration: float, frequency: int) -> str:
    if kind == "silence":
        return f"anullsrc=r=48000:cl=mono:d={duration}"
    return f"sine=frequency={frequency}:sample_rate=48000:duration={duration}"


def _make_fixture(
    output: Path,
    audio_parts: tuple[tuple[str, float], ...],
    codec_family: str,
    *,
    frame_rate: int = 10,
) -> Path:
    duration = sum(part_duration for _, part_duration in audio_parts)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=160x90:rate={frame_rate}:duration={duration}",
    ]
    for index, (kind, part_duration) in enumerate(audio_parts):
        command.extend(["-f", "lavfi", "-i", _audio_source(kind, part_duration, 440 + index * 110)])
    audio_inputs = "".join(f"[{index}:a]" for index in range(1, len(audio_parts) + 1))
    command.extend(
        ["-filter_complex", f"{audio_inputs}concat=n={len(audio_parts)}:v=0:a=1[a]", "-map", "0:v:0", "-map", "[a]"]
    )
    if codec_family == "av1-opus":
        command.extend(
            ["-c:v", "libaom-av1", "-cpu-used", "8", "-crf", "40", "-b:v", "0", "-c:a", "libopus", "-b:a", "64k"]
        )
    else:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "30",
                "-sc_threshold",
                "0",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
            ]
        )
    command.extend(["-g", "50", "-keyint_min", "50", "-shortest", str(output)])
    _run_media(command)
    return output


def _probe(path: Path) -> dict:
    result = _run_media(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(result.stdout)


def _assert_decodes(path: Path) -> None:
    _run_media(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0", "-f", "null", "-"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_media(path: Path, expected_duration: float, suffix: str) -> None:
    info = _probe(path)
    streams = info["streams"]
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    assert len(videos) == len(audios) == 1
    assert abs(float(info["format"]["duration"]) - expected_duration) <= DEFAULT_SILENCE_DURATION_TOLERANCE_SECONDS
    if suffix in {".mp4", ".mov", ".m4v"}:
        assert videos[0]["codec_name"] == "h264"
        assert audios[0]["codec_name"] == "aac"
        assert {"mov", "mp4"} & set(info["format"]["format_name"].split(","))
    elif suffix == ".webm":
        assert "webm" in info["format"]["format_name"].split(",")
    elif suffix == ".mkv":
        assert "matroska" in info["format"]["format_name"].split(",")
    _assert_decodes(path)


@pytest.mark.parametrize(
    ("regions", "duration", "margin", "expected"),
    [
        ([], 3.0, 0.1, [(0.0, 3.0)]),
        ([(1.0, 2.0)], 3.0, 0.1, [(0.0, 1.1), (1.9, 3.0)]),
        ([(2.0, 2.1)], 5.0, 0.1, [(0.0, 5.0)]),
        ([(0.0, 1.0), (4.0, 5.0)], 5.0, 0.1, [(0.0, 0.1), (0.9, 4.1), (4.9, 5.0)]),
        ([(0.0, 2.0)], 2.0, 0.1, [(0.0, 0.1), (1.9, 2.0)]),
        ([(0.0, 2.0)], 2.0, 0.0, []),
        ([(0.5, 1.5), (1.25, 2.0), (2.5, 3.0)], 4.0, 0.0, [(0.0, 0.5), (2.0, 2.5), (3.0, 4.0)]),
    ],
)
def test_build_keep_segments_preserves_both_margins(regions, duration, margin, expected) -> None:
    assert silence._build_keep_segments(regions, duration, margin) == expected


def test_filter_graph_resets_video_and_audio_timestamps() -> None:
    graph = silence._build_silence_filter_graph([(0.0, 1.25), (2.5, 3.75)])
    assert "trim=start=0:end=1.25,setpts=PTS-STARTPTS[v0]" in graph
    assert "atrim=start=2.5:end=3.75,asetpts=PTS-STARTPTS[a1]" in graph
    assert graph.endswith("[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]")


@pytest.mark.parametrize("codec_family", ["av1-opus", "h264-aac"])
@pytest.mark.parametrize(
    ("case", "parts", "expected_duration"),
    [
        ("zero", (("tone", 3.0),), 3.0),
        ("one", (("tone", 1.0), ("silence", 1.0), ("tone", 1.0)), 2.2),
        (
            "multiple",
            (("tone", 1.0), ("silence", 1.0), ("tone", 1.0), ("silence", 1.0), ("tone", 1.0)),
            3.4,
        ),
    ],
)
def test_real_media_matrix_keeps_streams_and_source(tmp_path, codec_family, case, parts, expected_duration) -> None:
    input_suffix = ".webm" if codec_family == "av1-opus" else ".mp4"
    source = _make_fixture(tmp_path / f"{codec_family}-{case}{input_suffix}", parts, codec_family)
    output = tmp_path / f"{codec_family}-{case}-output.mp4"
    before = _sha256(source)
    result = silence.ai_remove_silence(str(source), str(output), keep_margin=0.1)
    assert result == str(output)
    _assert_media(output, expected_duration, ".mp4")
    assert _sha256(source) == before


@pytest.fixture(scope="module")
def hostile_av1_source(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("silence-hostile")
    parts = (("tone", 1.0), ("silence", 1.0), ("tone", 1.0), ("silence", 1.0), ("tone", 1.0))
    return _make_fixture(root / "Ünicode source's \\ sparse.webm", parts, "av1-opus")


@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".m4v", ".mkv", ".webm"])
def test_real_av1_hostile_path_container_matrix(hostile_av1_source, suffix) -> None:
    output = hostile_av1_source.parent / f"quoted output's \\ artifact{suffix}"
    before = _sha256(hostile_av1_source)
    silence.ai_remove_silence(str(hostile_av1_source), str(output), keep_margin=0.1)
    _assert_media(output, 3.4, suffix)
    assert _sha256(hostile_av1_source) == before


def test_all_silence_keeps_default_edge_margins(tmp_path) -> None:
    source = _make_fixture(tmp_path / "all-silence.mp4", (("silence", 2.0),), "h264-aac")
    output = tmp_path / "edge-margins.mp4"
    silence.ai_remove_silence(str(source), str(output), keep_margin=0.1)
    _assert_media(output, 0.2, ".mp4")


def test_all_silence_explicit_zero_margin_fails_without_output(tmp_path) -> None:
    source = _make_fixture(tmp_path / "all-silence.mp4", (("silence", 2.0),), "h264-aac")
    output = tmp_path / "no-segments.mp4"
    before = _sha256(source)
    with pytest.raises(MCPVideoError, match="No segments to keep"):
        silence.ai_remove_silence(str(source), str(output), keep_margin=0)
    assert not output.exists()
    assert _sha256(source) == before


def test_many_fractional_segments_validate_with_fixed_tolerance(tmp_path) -> None:
    source = _make_fixture(tmp_path / "many-cuts.mp4", (("tone", 5.0),), "h264-aac", frame_rate=30)
    output = tmp_path / "many-cuts-output.mp4"
    segments = [(0.013 + index * 0.45, 0.313 + index * 0.45) for index in range(10)]
    expected_duration = sum(end - start for start, end in segments)
    with silence._atomic_output(str(output)) as staged:
        silence._render_keep_segments(str(source), segments, staged)
        silence._validate_silence_output(staged, expected_duration)
    _assert_media(output, expected_duration, ".mp4")


@pytest.mark.parametrize("existing_destination", [False, True])
def test_invalid_exit_zero_stage_is_never_promoted(tmp_path, monkeypatch, existing_destination) -> None:
    source = _make_fixture(tmp_path / "valid-source.mp4", (("tone", 1.0),), "h264-aac")
    output = tmp_path / "invalid-stage.mp4"
    sentinel = b"existing-destination"
    if existing_destination:
        output.write_bytes(sentinel)
    source_before = _sha256(source)

    def write_invalid(_video: str, _segments: list[tuple[float, float]], staged: str) -> None:
        Path(staged).write_bytes(b"not media")

    monkeypatch.setattr(silence, "_render_keep_segments", write_invalid)
    with pytest.raises(ProcessingError, match="staged output could not be probed"):
        silence.ai_remove_silence(str(source), str(output))
    if existing_destination:
        assert output.read_bytes() == sentinel
    else:
        assert not output.exists()
    assert _sha256(source) == source_before
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_decode_failure_preserves_existing_destination(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "destination.mp4"
    output.write_bytes(b"sentinel")
    monkeypatch.setattr(
        silence,
        "_run_ffprobe_json",
        lambda _path: {
            "format": {"duration": "1", "format_name": "mov,mp4"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}],
        },
    )
    monkeypatch.setattr(silence, "_detect_silence_regions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        silence, "_render_keep_segments", lambda _video, _segments, staged: Path(staged).write_bytes(b"stage")
    )
    monkeypatch.setattr(
        silence, "_run_command", lambda *_args, **_kwargs: (_ for _ in ()).throw(ProcessingError("decode", 1, "failed"))
    )
    with pytest.raises(ProcessingError, match="failed full media decode"):
        silence.ai_remove_silence(str(source), str(output))
    assert output.read_bytes() == b"sentinel"
    assert source.read_bytes() == b"source"


@pytest.mark.parametrize("returncode", [-1, 1])
def test_render_failure_never_promotes(tmp_path, monkeypatch, returncode) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "destination.mp4"
    output.write_bytes(b"sentinel")
    monkeypatch.setattr(
        silence,
        "_run_ffprobe_json",
        lambda _path: {"format": {"duration": "1", "format_name": "mov,mp4"}, "streams": []},
    )
    monkeypatch.setattr(silence, "_detect_silence_regions", lambda *_args, **_kwargs: [])

    def fail_command(*_args, **_kwargs):
        reason = "command timed out" if returncode == -1 else "encoder failed"
        raise ProcessingError("ffmpeg", returncode, reason)

    monkeypatch.setattr(silence, "_run_command", fail_command)
    with pytest.raises(ProcessingError):
        silence.ai_remove_silence(str(source), str(output))
    assert output.read_bytes() == b"sentinel"
    assert source.read_bytes() == b"source"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("alias_kind", ["same-path", "relative-path", "hardlink"])
def test_output_may_not_alias_input(tmp_path, monkeypatch, alias_kind) -> None:
    source = _make_fixture(tmp_path / "source.mp4", (("tone", 1.0),), "h264-aac")
    before = _sha256(source)
    if alias_kind == "hardlink":
        output = tmp_path / "hardlink.mp4"
        os.link(source, output)
        video_arg, output_arg = str(source), str(output)
    elif alias_kind == "relative-path":
        monkeypatch.chdir(tmp_path)
        video_arg, output_arg = "source.mp4", str(source)
    else:
        video_arg = output_arg = str(source)
    with pytest.raises(MCPVideoError, match="output path aliases an input"):
        silence.ai_remove_silence(video_arg, output_arg)
    assert _sha256(source) == before
