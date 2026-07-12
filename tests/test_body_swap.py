"""Real-media tests for the guarded body-swap engine primitive."""

from __future__ import annotations

import inspect
import os
import subprocess
from pathlib import Path

import pytest

from kinocut.errors import InputFileError, MCPVideoError
from kinocut.engine_runtime_utils import _ffmpeg, _ffprobe
from kinocut.ffmpeg_helpers import _get_video_duration, _run_ffprobe_json


def _clip(
    path,
    *,
    duration: float,
    audio_streams: int = 1,
    color: str = "blue",
    base_frequency: int = 440,
):
    inputs = ["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d={duration}"]
    for index in range(audio_streams):
        inputs.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={base_frequency + index * 220}:duration={duration}",
            ]
        )
    maps = ["-map", "0:v:0"]
    for index in range(audio_streams):
        maps.extend(["-map", f"{index + 1}:a:0"])
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            *inputs,
            *maps,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


def _long_audio(path, *, tail_frequency: int):
    expression = f"aevalsrc=if(lt(t\\,107)\\,sin(2*PI*440*t)\\,sin(2*PI*{tail_frequency}*t)):s=48000:d=108"
    subprocess.run(
        [_ffmpeg(), "-y", "-f", "lavfi", "-i", expression, "-c:a", "aac", str(path)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


def _audio_packet_count(path) -> int:
    result = subprocess.run(
        [
            _ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-count_packets",
            "-show_entries",
            "stream=nb_read_packets",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return int(result.stdout.strip())


@pytest.fixture
def clip_a(tmp_path):
    return _clip(tmp_path / "clip-a.mp4", duration=1.0, color="blue")


@pytest.fixture
def clip_b(tmp_path):
    return _clip(tmp_path / "clip-b.mp4", duration=1.0, color="red")


def test_body_swap_preserves_approved_audio_by_default(tmp_path, clip_a, clip_b):
    from kinocut.engine_body_swap import body_swap

    result = body_swap(
        video_source=str(clip_b),
        audio_source=str(clip_a),
        output_path=str(tmp_path / "output.mp4"),
    )

    proof = result["preservation_proofs"][0]
    assert proof["verdict"] == "preserved"
    assert proof["source_fingerprint"] == proof["output_fingerprint"]


def test_verified_body_swap_uses_inherited_anonymous_sources(tmp_path, clip_a, clip_b):
    from kinocut.engine_body_swap import body_swap
    from kinocut.source_identity import stream_source_identity

    output = tmp_path / "verified-output.mp4"
    result = body_swap(
        str(clip_b),
        str(clip_a),
        str(output),
        verified_source_identities=(
            stream_source_identity(str(clip_b)),
            stream_source_identity(str(clip_a)),
        ),
    )

    assert result["preservation_proofs"][0]["verdict"] == "preserved"
    assert output.exists()
    assert not list(tmp_path.glob(".body-swap.*"))


def test_duration_mismatch_rejected_unless_explicit(tmp_path):
    from kinocut.engine_body_swap import body_swap

    clip_10s = _clip(tmp_path / "audio-long.mp4", duration=1.0)
    clip_7s = _clip(tmp_path / "video-short.mp4", duration=0.7)

    with pytest.raises(MCPVideoError) as excinfo:
        body_swap(
            video_source=str(clip_7s),
            audio_source=str(clip_10s),
            output_path=str(tmp_path / "output.mp4"),
        )

    assert excinfo.value.code in {"validation_error", "protected_element_change"}


def test_multi_stream_audio_is_preserved(tmp_path):
    from kinocut.engine_body_swap import body_swap

    audio = _clip(tmp_path / "two-audio.mp4", duration=1.0, audio_streams=2)
    video = _clip(tmp_path / "video.mp4", duration=1.0, color="red")
    result = body_swap(str(video), str(audio), str(tmp_path / "output.mp4"))
    output_streams = _run_ffprobe_json(result["output_path"])["streams"]

    assert sum(stream["codec_type"] == "audio" for stream in output_streams) == 2
    assert result["preservation_proofs"][0]["verdict"] == "preserved"


def test_audio_fingerprint_includes_packet_payload_identity(tmp_path):
    from kinocut.engine_body_swap import _audio_fingerprint

    low_tone = _clip(tmp_path / "low.mp4", duration=1.0, base_frequency=440)
    high_tone = _clip(tmp_path / "high.mp4", duration=1.0, base_frequency=880)

    assert _audio_fingerprint(str(low_tone)) != _audio_fingerprint(str(high_tone))


def test_audio_fingerprint_covers_payload_after_first_5000_packets(tmp_path):
    from kinocut.engine_body_swap import _audio_fingerprint

    first = _long_audio(tmp_path / "tail-880.m4a", tail_frequency=880)
    second = _long_audio(tmp_path / "tail-990.m4a", tail_frequency=990)

    assert _audio_packet_count(first) > 5000
    assert _audio_packet_count(second) > 5000
    assert _audio_fingerprint(str(first)) != _audio_fingerprint(str(second))


@pytest.mark.parametrize(
    ("policy", "video_duration", "audio_duration", "expected_verdict"),
    (
        ("pad_video", 0.6, 1.0, "preserved"),
        ("trim_video", 1.0, 0.6, "preserved"),
        ("trim_audio", 0.6, 1.0, "changed"),
    ),
)
def test_explicit_duration_policies(tmp_path, policy, video_duration, audio_duration, expected_verdict):
    from kinocut.engine_body_swap import body_swap

    video = _clip(tmp_path / f"video-{policy}.mp4", duration=video_duration)
    audio = _clip(tmp_path / f"audio-{policy}.mp4", duration=audio_duration, color="red")
    result = body_swap(str(video), str(audio), str(tmp_path / f"output-{policy}.mp4"), duration_policy=policy)

    assert _get_video_duration(result["output_path"]) == pytest.approx(
        min(video_duration, audio_duration) if policy != "pad_video" else audio_duration,
        abs=0.12,
    )
    assert result["preservation_proofs"][0]["verdict"] == expected_verdict


def test_unknown_duration_policy_is_rejected(tmp_path, clip_a, clip_b):
    from kinocut.engine_body_swap import body_swap

    with pytest.raises(MCPVideoError) as excinfo:
        body_swap(str(clip_b), str(clip_a), str(tmp_path / "output.mp4"), duration_policy="shortest")
    assert excinfo.value.code == "validation_error"


def test_declared_preservation_fails_closed_when_fingerprint_changes(tmp_path, clip_a, clip_b, monkeypatch):
    import kinocut.engine_body_swap as engine

    original = engine._audio_fingerprint
    calls = 0

    def changed_output(path):
        nonlocal calls
        calls += 1
        fingerprint = original(path)
        return fingerprint if calls == 1 else "sha256:" + "f" * 64

    monkeypatch.setattr(engine, "_audio_fingerprint", changed_output)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(str(clip_b), str(clip_a), str(tmp_path / "output.mp4"))
    assert excinfo.value.code == "protected_element_change"


def test_body_swap_runs_engine_owned_protection_precheck(tmp_path, clip_a, clip_b):
    from kinocut.aivideo.protection import protect
    from kinocut.contracts.protection import ProtectedElement
    from kinocut.engine_body_swap import _source_fingerprint, body_swap
    from kinocut.projectstore import open_project
    from tests.contracts_fixtures import protection_kwargs

    project = open_project(tmp_path / "project")
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="source_asset",
                dependency_fingerprint=_source_fingerprint(str(clip_b)),
            )
        ),
    )
    output = tmp_path / "blocked.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        body_swap(str(clip_b), str(clip_a), str(output), project=project)

    assert excinfo.value.code == "protected_element_change"
    assert not output.exists()


def test_body_swap_precheck_uses_exact_audio_fingerprint(tmp_path, clip_a, clip_b):
    from kinocut.aivideo.protection import protect
    from kinocut.contracts.protection import ProtectedElement
    from kinocut.engine_body_swap import _audio_fingerprint, body_swap
    from kinocut.projectstore import open_project
    from tests.contracts_fixtures import protection_kwargs

    project = open_project(tmp_path / "project")
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="audio_stream",
                dependency_fingerprint=_audio_fingerprint(str(clip_a)),
            )
        ),
    )
    output = tmp_path / "blocked-audio.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        body_swap(str(clip_b), str(clip_a), str(output), project=project)

    assert excinfo.value.code == "protected_element_change"
    assert not output.exists()


def test_body_swap_has_no_force_path():
    from kinocut.engine_body_swap import body_swap

    assert "force" not in inspect.signature(body_swap).parameters


def test_body_swap_rejects_direct_output_alias_before_render(clip_a, clip_b, monkeypatch):
    import kinocut.engine_body_swap as engine

    before = Path(clip_b).read_bytes()
    rendered = False

    def unexpected_render(args):
        nonlocal rendered
        rendered = True

    monkeypatch.setattr(engine, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(str(clip_b), str(clip_a), str(clip_b))

    assert excinfo.value.code == "invalid_output_path"
    assert not rendered
    assert Path(clip_b).read_bytes() == before


def test_body_swap_rejects_hardlink_output_alias_before_render(tmp_path, clip_a, clip_b, monkeypatch):
    import kinocut.engine_body_swap as engine

    output = tmp_path / "hardlink.mp4"
    os.link(clip_a, output)
    before = Path(clip_a).read_bytes()
    rendered = False

    def unexpected_render(args):
        nonlocal rendered
        rendered = True

    monkeypatch.setattr(engine, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(str(clip_b), str(clip_a), str(output))

    assert excinfo.value.code == "invalid_output_path"
    assert not rendered
    assert Path(clip_a).read_bytes() == before


def test_source_fingerprint_translates_read_failure(tmp_path, monkeypatch):
    from kinocut.engine_body_swap import _source_fingerprint

    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")

    def failed_open(*args, **kwargs):
        raise OSError("simulated read race")

    monkeypatch.setattr("kinocut.source_identity.os.open", failed_open)
    with pytest.raises(InputFileError):
        _source_fingerprint(str(source))
