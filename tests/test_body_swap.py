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
from kinocut.source_identity import immutable_verified_snapshot_available


pytestmark = pytest.mark.skipif(
    not immutable_verified_snapshot_available(),
    reason="immutable verified source snapshots are unavailable",
)


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
        ("trim_audio", 0.6, 1.0, "preserved"),
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


def test_pad_video_authorization_cannot_be_replayed_for_trim_audio(tmp_path):
    from kinocut.aivideo.protection import (
        MutationIntent,
        assert_no_protected_collision,
        mutation_fingerprint,
        protect,
    )
    from kinocut.contracts.protection import ProtectedElement
    from kinocut.contracts.review import ReviewDecision
    from kinocut.engine_body_swap import (
        _audio_fingerprint,
        _body_swap_parameters_fingerprint,
        _source_fingerprint,
        body_swap,
    )
    from kinocut.projectstore import append_record, open_project
    from tests.contracts_fixtures import protection_kwargs, review_decision_kwargs

    video = _clip(tmp_path / "short-video.mp4", duration=0.6)
    audio = _clip(tmp_path / "protected-audio.mp4", duration=1.0, color="red")
    project = open_project(tmp_path / "project")
    audio_fingerprint = _audio_fingerprint(str(audio))
    original = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=audio_fingerprint,
                dependency_fingerprint=audio_fingerprint,
            )
        ),
    )
    lock = protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="audio_stream",
                dependency_fingerprint=audio_fingerprint,
                human_approval_ref=original.record_id,
            )
        ),
    )
    pad_video_intent = MutationIntent(
        operation="body_swap",
        source_asset=_source_fingerprint(str(video)),
        audio_stream=audio_fingerprint,
        operation_parameters=_body_swap_parameters_fingerprint("pad_video"),
    )
    approval = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=mutation_fingerprint(pad_video_intent),
                dependency_fingerprint=mutation_fingerprint(pad_video_intent),
                rationale="authorize pad_video while preserving protected audio",
                source_record_ids=(lock.record_id, original.record_id),
            )
        ),
    )
    authorized_pad = pad_video_intent.model_copy(update={"authorization_decision_ids": (approval.record_id,)})
    assert_no_protected_collision(project, authorized_pad)

    with pytest.raises(MCPVideoError) as excinfo:
        body_swap(
            str(video),
            str(audio),
            str(tmp_path / "must-not-trim-audio.mp4"),
            duration_policy="trim_audio",
            project=project,
            authorization_decision_ids=(approval.record_id,),
        )

    assert excinfo.value.code == "protected_element_change"
    assert not (tmp_path / "must-not-trim-audio.mp4").exists()


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


def _trim_audio_args(args: list) -> tuple[str, str, str]:
    """Pull (video_input, bound, output) from a body_swap render argv list."""
    inputs = [args[i + 1] for i, arg in enumerate(args) if arg == "-i"]
    bound = next(args[i + 1] for i, arg in enumerate(args) if arg == "-t" and i + 1 < len(args))
    return inputs[0], bound, args[-1]


def test_trim_audio_rejects_substituted_audio_of_matching_duration(tmp_path, monkeypatch):
    """RED: trim_audio must reject output whose audio is from a different source.

    A hostile renderer swaps in a clip of the same trim duration and codec
    topology; under the old whole-stream proof this passes because
    preservation is not required for trim_audio. The bounded decoded-prefix
    evidence must catch the substitution.
    """
    import kinocut.engine_body_swap as engine
    from kinocut.ffmpeg_helpers import _run_ffmpeg as real_run_ffmpeg

    short_video = _clip(tmp_path / "ta-sub-short-video.mp4", duration=0.6, color="blue")
    long_audio = _clip(tmp_path / "ta-sub-long-audio.mp4", duration=1.0, base_frequency=440, color="red")
    substitute = _clip(tmp_path / "ta-sub-substitute.mp4", duration=0.6, base_frequency=880, color="green")

    def hostile_render(args, *, pass_fds=()):
        video_input, bound, output = _trim_audio_args(args)
        return real_run_ffmpeg(
            [
                "-i",
                video_input,
                "-i",
                str(substitute),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-t",
                bound,
                output,
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr(engine, "_run_ffmpeg", hostile_render)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(
            str(short_video),
            str(long_audio),
            str(tmp_path / "ta-sub-hostile-output.mp4"),
            duration_policy="trim_audio",
        )
    assert excinfo.value.code == "protected_element_change"


def test_trim_audio_rejects_corrupt_audio_of_matching_duration(tmp_path, monkeypatch):
    """RED: trim_audio must reject output whose audio samples are perturbed.

    A hostile renderer re-encodes the approved audio with a tiny volume nudge,
    preserving duration and codec topology but mutating the decoded samples.
    """
    import kinocut.engine_body_swap as engine
    from kinocut.ffmpeg_helpers import _run_ffmpeg as real_run_ffmpeg

    short_video = _clip(tmp_path / "ta-corr-short-video.mp4", duration=0.6, color="blue")
    long_audio = _clip(tmp_path / "ta-corr-long-audio.mp4", duration=1.0, base_frequency=440, color="red")

    def hostile_render(args, *, pass_fds=()):
        inputs = [args[i + 1] for i, arg in enumerate(args) if arg == "-i"]
        video_input, audio_input = inputs[0], inputs[1]
        _, bound, output = _trim_audio_args(args)
        return real_run_ffmpeg(
            [
                "-i",
                video_input,
                "-i",
                audio_input,
                "-filter_complex",
                "[1:a]volume=1.05[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-t",
                bound,
                output,
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr(engine, "_run_ffmpeg", hostile_render)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(
            str(short_video),
            str(long_audio),
            str(tmp_path / "ta-corr-corrupt-output.mp4"),
            duration_policy="trim_audio",
        )
    assert excinfo.value.code == "protected_element_change"


def test_trim_audio_rejects_substituted_audio_via_verified_descriptors(tmp_path, monkeypatch):
    """RED: trim_audio must reject hostile renders reached through verified fds."""
    import kinocut.engine_body_swap as engine
    from kinocut.ffmpeg_helpers import _run_ffmpeg as real_run_ffmpeg
    from kinocut.source_identity import stream_source_identity

    short_video = _clip(tmp_path / "ta-ver-short-video.mp4", duration=0.6, color="blue")
    long_audio = _clip(tmp_path / "ta-ver-long-audio.mp4", duration=1.0, base_frequency=440, color="red")
    substitute = _clip(tmp_path / "ta-ver-substitute.mp4", duration=0.6, base_frequency=990, color="green")

    def hostile_render(args, *, pass_fds=()):
        video_input, bound, output = _trim_audio_args(args)
        # Pass the inherited descriptors through so the legitimate fd-backed
        # video is read; the substitute audio is a regular file the subprocess
        # opens by path.
        return real_run_ffmpeg(
            [
                "-i",
                video_input,
                "-i",
                str(substitute),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-t",
                bound,
                output,
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr(engine, "_run_ffmpeg", hostile_render)
    with pytest.raises(MCPVideoError) as excinfo:
        engine.body_swap(
            str(short_video),
            str(long_audio),
            str(tmp_path / "ta-ver-hostile-output.mp4"),
            duration_policy="trim_audio",
            verified_source_identities=(
                stream_source_identity(str(short_video)),
                stream_source_identity(str(long_audio)),
            ),
        )
    assert excinfo.value.code == "protected_element_change"
    assert not list(tmp_path.glob(".body-swap.*"))


def test_trim_audio_legitimate_cut_preserves_approved_prefix(tmp_path):
    """GREEN contract: a faithful trim_audio cut returns a preserved prefix proof."""
    from kinocut.engine_body_swap import body_swap

    short_video = _clip(tmp_path / "ta-ok-short-video.mp4", duration=0.6, color="blue")
    long_audio = _clip(tmp_path / "ta-ok-long-audio.mp4", duration=1.0, base_frequency=440, color="red")
    result = body_swap(
        str(short_video),
        str(long_audio),
        str(tmp_path / "ta-ok-output.mp4"),
        duration_policy="trim_audio",
    )
    proof = result["preservation_proofs"][0]
    assert proof["verdict"] == "preserved"
    assert proof["expected"] == "approved_audio_prefix_preserved"
    assert proof["source_fingerprint"] == proof["output_fingerprint"]
