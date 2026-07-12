"""Guarded body replacement with approved-audio preservation evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import Any

from .aivideo.protection import MutationIntent, assert_no_protected_collision
from .contracts import PreservationProof
from .defaults import (
    DEFAULT_BODY_SWAP_DURATION_TOLERANCE_SECONDS,
    DEFAULT_FFMPEG_TIMEOUT,
)
from .errors import InputFileError, MCPVideoError, ProcessingError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _get_video_duration,
    _run_ffmpeg,
    _run_ffprobe_json,
    _run_command,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .projectstore import Project
from .rescue.verifier import _av_end_delta, _packets, _stream_counts
from .source_identity import (
    SourceIdentity,
    VerifiedSource,
    assert_source_identity,
    copy_verified_snapshot,
    stream_source_identity,
)
from .validation import BODY_SWAP_DURATION_POLICIES
from .limits import FFPROBE_TIMEOUT

_AUDIO_STREAM_FIELDS = (
    "codec_name",
    "codec_tag_string",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
    "bits_per_sample",
    "time_base",
    "extradata_size",
    "nb_read_packets",
)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_fingerprint(path: str) -> str:
    try:
        return stream_source_identity(path).asset_id
    except MCPVideoError:
        raise InputFileError(path, "Cannot read input while fingerprinting") from None


def _body_swap_parameters_fingerprint(duration_policy: str | None) -> str:
    """Bind authorization to the exact declared duration behavior."""

    payload = {"duration_policy": duration_policy or "reject_mismatch"}
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def _assert_bound_identity(path: str, expected: SourceIdentity) -> None:
    """Fail privately if current bytes no longer equal a verified identity."""

    try:
        assert_source_identity(path, expected)
    except MCPVideoError as exc:
        raise _validation_error("verified source identity is unavailable", "wave3_asset_integrity_failed") from exc


def _assert_bound_identities(paths: tuple[str, str], identities: tuple[SourceIdentity, SourceIdentity] | None) -> None:
    if identities is None:
        return
    for path, expected in zip(paths, identities, strict=True):
        _assert_bound_identity(path, expected)


def _audio_streams_with_counts(path: str, *, pass_fds: tuple[int, ...] = ()) -> list[dict[str, Any]]:
    result = _run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-count_packets",
            "-show_entries",
            "stream=index,codec_name,codec_tag_string,sample_fmt,sample_rate,"
            "channels,channel_layout,bits_per_sample,time_base,extradata_size,nb_read_packets",
            "-of",
            "json",
            path,
        ],
        timeout=FFPROBE_TIMEOUT,
        pass_fds=pass_fds,
    )
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError as exc:
        raise ProcessingError("ffprobe audio stream counts", 0, "invalid stream JSON") from exc
    if not streams or any(stream.get("nb_read_packets") is None for stream in streams):
        raise ProcessingError("ffprobe audio stream counts", 0, "missing exact packet count")
    return streams


def _parse_stream_hashes(stdout: str) -> list[str]:
    """Normalize ffmpeg ``-f streamhash`` lines into ``sha256:`` tokens, in order."""
    hashes: list[str] = []
    for line in stdout.splitlines():
        marker = "SHA256="
        if marker not in line:
            continue
        value = line.split(marker, 1)[1].strip().lower()
        if len(value) == 64 and all(character in "0123456789abcdef" for character in value):
            hashes.append("sha256:" + value)
    return hashes


def _whole_audio_hashes(path: str, expected_streams: int, *, pass_fds: tuple[int, ...] = ()) -> list[str]:
    result = _run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            "0:a",
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        timeout=DEFAULT_FFMPEG_TIMEOUT,
        pass_fds=pass_fds,
    )
    hashes = _parse_stream_hashes(result.stdout)
    if len(hashes) != expected_streams:
        raise ProcessingError("ffmpeg whole audio stream hash", 0, "incomplete stream hashes")
    return hashes


def _bounded_audio_pcm_hashes(
    path: str,
    bound_seconds: float,
    expected_streams: int,
    *,
    pass_fds: tuple[int, ...] = (),
) -> list[str]:
    """Hash the first ``bound_seconds`` of every audio stream as decoded PCM.

    Re-decoding to ``pcm_s16le`` is independent of muxer packet layout, so this
    catches sample-level substitution or re-encode corruption even when the
    container-level packet sequence and stream topology look plausible. The
    bound is shared between the approved source and the rendered output so a
    legitimate ``-c:a copy -t`` cut produces identical per-stream hashes.
    """
    bound = str(_sanitize_ffmpeg_number(bound_seconds, "audio bound"))
    result = _run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            "0:a",
            "-t",
            bound,
            "-c:a",
            "pcm_s16le",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        timeout=DEFAULT_FFMPEG_TIMEOUT,
        pass_fds=pass_fds,
    )
    hashes = _parse_stream_hashes(result.stdout)
    if len(hashes) != expected_streams:
        raise ProcessingError("ffmpeg bounded audio PCM hash", 0, "incomplete stream hashes")
    return hashes


def _supplemental_evidence(
    raw: dict[str, Any],
    packets: list[dict[str, Any]],
) -> dict[str, Any]:
    audio_indices = {
        int(stream.get("index", -1)): position
        for position, stream in enumerate(raw.get("streams", []))
        if stream.get("codec_type") == "audio"
    }
    audio_packets = []
    for packet in packets:
        index = int(packet.get("stream_index", -1))
        if index not in audio_indices:
            continue
        audio_packets.append(
            {
                "stream": audio_indices[index],
                **{field: packet.get(field) for field in ("pts_time", "dts_time", "duration_time")},
            }
        )
    return {
        "bounded_audio_packets": audio_packets,
        "stream_counts": _stream_counts(raw),
        "av_end_delta": _av_end_delta(raw, packets),
    }


def _audio_evidence(path: str, *, pass_fds: tuple[int, ...] = ()) -> dict[str, Any]:
    if not pass_fds:
        path = _validate_input_path(path)
    raw = _run_ffprobe_json(path, pass_fds=pass_fds)
    streams = _audio_streams_with_counts(path, pass_fds=pass_fds)
    verifier_packets = _packets(path, pass_fds=pass_fds)
    stream_count = _stream_counts(raw).get("audio", 0)
    if stream_count != len(streams):
        raise ProcessingError("ffprobe audio stream counts", 0, "inconsistent stream counts")
    return {
        "identity": {
            "streams": [{field: stream.get(field) for field in _AUDIO_STREAM_FIELDS} for stream in streams],
            "audio_stream_count": stream_count,
            "whole_stream_hashes": _whole_audio_hashes(path, stream_count, pass_fds=pass_fds),
        },
        "supplemental": _supplemental_evidence(raw, verifier_packets),
    }


def _audio_fingerprint(path: str, *, pass_fds: tuple[int, ...] = ()) -> str:
    identity = _audio_evidence(path, pass_fds=pass_fds)["identity"]
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(payload)


def _validation_error(message: str, code: str = "validation_error") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _reject_output_alias(output_path: str, inputs: tuple[str, str]) -> None:
    output_resolved = os.path.realpath(output_path)
    for input_path in inputs:
        if output_resolved == os.path.realpath(input_path):
            raise _validation_error("output path aliases an input", "invalid_output_path")
        if not os.path.exists(output_path):
            continue
        try:
            if os.path.samefile(output_path, input_path):
                raise _validation_error("output path aliases an input", "invalid_output_path")
        except OSError:
            raise _validation_error("cannot safely verify output identity", "invalid_output_path") from None


def _precheck(
    project: Project | None,
    video_source: str,
    audio_source: str,
    authorization_decision_ids: tuple[str, ...],
    duration_policy: str | None,
    *,
    source_identity: SourceIdentity | None = None,
    pass_fds: tuple[int, ...] = (),
) -> None:
    if project is None:
        return
    assert_no_protected_collision(
        project,
        MutationIntent(
            operation="body_swap",
            source_asset=(
                source_identity.asset_id if source_identity is not None else _source_fingerprint(video_source)
            ),
            audio_stream=(
                _audio_fingerprint(audio_source, pass_fds=pass_fds) if pass_fds else _audio_fingerprint(audio_source)
            ),
            operation_parameters=_body_swap_parameters_fingerprint(duration_policy),
            authorization_decision_ids=authorization_decision_ids,
        ),
    )


def _proof(
    source_fingerprint: str,
    output_path: str,
    *,
    preservation_required: bool,
    pass_fds: tuple[int, ...] = (),
) -> PreservationProof:
    output_fingerprint = (
        _audio_fingerprint(output_path, pass_fds=pass_fds) if pass_fds else _audio_fingerprint(output_path)
    )
    proof = PreservationProof(
        expected="approved_audio_identical",
        method="whole_stream_and_packet_fingerprint",
        source_fingerprint=source_fingerprint,
        output_fingerprint=output_fingerprint,
        verdict="preserved" if source_fingerprint == output_fingerprint else "changed",
    )
    if preservation_required and proof.verdict != "preserved":
        raise _validation_error("approved audio preservation gate failed", "protected_element_change")
    return proof


# Topology fields preserved by ``-c:a copy``: mutations here would let a
# hostile renderer swap codec or channel layout while keeping samples
# superficially plausible, so they are gated independently of the PCM hash.
_AUDIO_TOPOLOGY_FIELDS = (
    "codec_name",
    "sample_fmt",
    "sample_rate",
    "channels",
    "channel_layout",
)


def _require_matching_audio_topology(
    source_identity: dict[str, Any],
    output_identity: dict[str, Any],
) -> None:
    """Reject stream-count or per-stream topology drift under trim_audio."""
    source_count = source_identity.get("audio_stream_count")
    output_count = output_identity.get("audio_stream_count")
    if source_count != output_count:
        raise _validation_error(
            "audio stream count changed under trim_audio",
            "protected_element_change",
        )
    source_streams = source_identity.get("streams", [])
    output_streams = output_identity.get("streams", [])
    if len(source_streams) != len(output_streams):
        raise _validation_error(
            "audio stream metadata changed under trim_audio",
            "protected_element_change",
        )
    for source_stream, output_stream in zip(source_streams, output_streams, strict=True):
        for field in _AUDIO_TOPOLOGY_FIELDS:
            if source_stream.get(field) != output_stream.get(field):
                raise _validation_error(
                    "audio stream topology changed under trim_audio",
                    "protected_element_change",
                )


def _evidence_fingerprint(hashes: list[str]) -> str:
    """Stable sha256 over a list of per-stream hashes for proof records."""
    return _sha256("|".join(hashes).encode())


def _trim_audio_proof(
    source_path: str,
    output_path: str,
    bound_seconds: float,
    *,
    source_pass_fds: tuple[int, ...] = (),
) -> PreservationProof:
    """Prove the rendered output is a real bounded prefix of the approved audio.

    The whole-stream hash cannot match under ``trim_audio`` (the output is
    intentionally shorter), so the proof re-decodes the first ``bound_seconds``
    of every audio stream from both source and output to canonical PCM and
    requires per-stream equality. Topology fields (codec, sample rate, channel
    layout) are gated independently so a stream swap that preserves samples but
    mutates layout cannot slip through. Duration is bounded by the supplied
    ``bound_seconds`` so the comparison window is the same on both sides.
    """
    source_identity = _audio_evidence(source_path, pass_fds=source_pass_fds)["identity"]
    output_identity = _audio_evidence(output_path)["identity"]
    _require_matching_audio_topology(source_identity, output_identity)
    stream_count = int(source_identity["audio_stream_count"])
    source_hashes = _bounded_audio_pcm_hashes(
        source_path,
        bound_seconds,
        stream_count,
        pass_fds=source_pass_fds,
    )
    output_hashes = _bounded_audio_pcm_hashes(
        output_path,
        bound_seconds,
        stream_count,
    )
    source_fingerprint = _evidence_fingerprint(source_hashes)
    output_fingerprint = _evidence_fingerprint(output_hashes)
    if source_hashes != output_hashes:
        raise _validation_error(
            "approved audio trim prefix changed",
            "protected_element_change",
        )
    return PreservationProof(
        expected="approved_audio_prefix_preserved",
        method="bounded_decoded_pcm_and_topology",
        source_fingerprint=source_fingerprint,
        output_fingerprint=output_fingerprint,
        verdict="preserved",
    )


def _duration_policy_error(policy: str) -> MCPVideoError:
    return _validation_error(f"{policy} cannot resolve the supplied duration direction")


def _render_args(
    video_source: str,
    audio_source: str,
    output_path: str,
    policy: str | None,
    video_duration: float,
    audio_duration: float,
) -> list[str]:
    inputs = ["-i", video_source, "-i", audio_source]
    if policy == "pad_video":
        if video_duration > audio_duration:
            raise _duration_policy_error(policy)
        delta = _sanitize_ffmpeg_number(audio_duration - video_duration, "pad duration")
        safe_delta = _escape_ffmpeg_filter_value(str(delta))
        return [
            *inputs,
            "-filter_complex",
            f"[0:v:0]tpad=stop_mode=clone:stop_duration={safe_delta}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            output_path,
        ]
    if policy == "trim_video":
        if video_duration < audio_duration:
            raise _duration_policy_error(policy)
        return [
            *inputs,
            "-map",
            "0:v:0",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-shortest",
            output_path,
        ]
    args = [*inputs, "-map", "0:v:0", "-map", "1:a", "-c:v", "copy", "-c:a", "copy"]
    if policy == "trim_audio":
        if audio_duration < video_duration:
            raise _duration_policy_error(policy)
        args.extend(["-t", str(_sanitize_ffmpeg_number(video_duration, "trim duration"))])
    return [*args, output_path]


def _render_from_descriptors(
    sources: tuple[VerifiedSource, VerifiedSource],
    rendered: Path,
    originals: tuple[str, str],
    duration_policy: str | None,
    project: Project | None,
    authorization_decision_ids: tuple[str, ...],
) -> PreservationProof:
    video, audio = sources
    pass_fds = (video.fd, audio.fd)
    video_duration = _get_video_duration(video.path, pass_fds=pass_fds)
    audio_duration = _get_video_duration(audio.path, pass_fds=pass_fds)
    mismatch = abs(video_duration - audio_duration) > DEFAULT_BODY_SWAP_DURATION_TOLERANCE_SECONDS
    if mismatch and duration_policy is None:
        raise _validation_error("body-swap durations differ; choose an explicit policy")
    _precheck(
        project,
        video.path,
        audio.path,
        authorization_decision_ids,
        duration_policy,
        source_identity=video.identity,
        pass_fds=pass_fds,
    )
    source_fingerprint = _audio_fingerprint(audio.path, pass_fds=pass_fds)
    _run_ffmpeg(
        _render_args(
            video.path,
            audio.path,
            str(rendered),
            duration_policy,
            video_duration,
            audio_duration,
        ),
        pass_fds=pass_fds,
    )
    _assert_bound_identities(originals, (video.identity, audio.identity))
    if duration_policy == "trim_audio":
        return _trim_audio_proof(
            audio.path,
            str(rendered),
            video_duration,
            source_pass_fds=pass_fds,
        )
    return _proof(
        source_fingerprint,
        str(rendered),
        preservation_required=True,
    )


def _guarded_render(
    video_source: str,
    audio_source: str,
    output_path: str,
    duration_policy: str | None,
    project: Project | None,
    authorization_decision_ids: tuple[str, ...],
    identities: tuple[SourceIdentity, SourceIdentity],
) -> PreservationProof:
    """Publish only after anonymous inputs and private workspace are cleaned."""

    staging: Path | None = None
    staging_fd = -1
    try:
        staging_fd, name = tempfile.mkstemp(
            dir=Path(output_path).parent,
            prefix=".body-swap.publish.",
            suffix=Path(output_path).suffix,
        )
        staging = Path(name)
        os.close(staging_fd)
        staging_fd = -1
        with (
            ExitStack() as source_stack,
            tempfile.TemporaryDirectory(dir=Path(output_path).parent, prefix=".body-swap.") as workspace,
        ):
            root = Path(workspace)
            video = copy_verified_snapshot(
                video_source,
                root / f"video{Path(video_source).suffix}",
                identities[0],
            )
            source_stack.callback(video.close)
            audio = copy_verified_snapshot(
                audio_source,
                root / f"audio{Path(audio_source).suffix}",
                identities[1],
            )
            source_stack.callback(audio.close)
            rendered = root / f"rendered{Path(output_path).suffix}"
            proof = _render_from_descriptors(
                (video, audio),
                rendered,
                (video_source, audio_source),
                duration_policy,
                project,
                authorization_decision_ids,
            )
            os.replace(rendered, staging)
        os.replace(staging, output_path)
        staging = None
        return proof
    except OSError:
        raise ProcessingError("body-swap guarded transaction", 0, "private transaction failed") from None
    finally:
        if staging_fd >= 0:
            with suppress(OSError):
                os.close(staging_fd)
        if staging is not None:
            with suppress(OSError):
                staging.unlink(missing_ok=True)


def body_swap(
    video_source: str,
    audio_source: str,
    output_path: str,
    *,
    duration_policy: str | None = None,
    project: Project | None = None,
    authorization_decision_ids: tuple[str, ...] = (),
    verified_source_identities: tuple[SourceIdentity, SourceIdentity] | None = None,
) -> dict[str, Any]:
    """Replace a clip's body while preserving every approved audio stream."""

    video_source = _validate_input_path(video_source)
    audio_source = _validate_input_path(audio_source)
    _validate_output_path(output_path)
    _reject_output_alias(output_path, (video_source, audio_source))
    _assert_bound_identities(
        (video_source, audio_source),
        verified_source_identities,
    )
    if duration_policy is not None and duration_policy not in BODY_SWAP_DURATION_POLICIES:
        raise _validation_error("unsupported body-swap duration policy")
    if verified_source_identities is not None:
        proof = _guarded_render(
            video_source,
            audio_source,
            output_path,
            duration_policy,
            project,
            authorization_decision_ids,
            verified_source_identities,
        )
    else:
        video_duration = _get_video_duration(video_source)
        audio_duration = _get_video_duration(audio_source)
        mismatch = abs(video_duration - audio_duration) > DEFAULT_BODY_SWAP_DURATION_TOLERANCE_SECONDS
        if mismatch and duration_policy is None:
            raise _validation_error("body-swap durations differ; choose an explicit policy")
        _precheck(project, video_source, audio_source, authorization_decision_ids, duration_policy)
        render_args = _render_args(
            video_source,
            audio_source,
            output_path,
            duration_policy,
            video_duration,
            audio_duration,
        )
        _run_ffmpeg(render_args)
        if duration_policy == "trim_audio":
            proof = _trim_audio_proof(audio_source, output_path, video_duration)
        else:
            source_fingerprint = _audio_fingerprint(audio_source)
            proof = _proof(
                source_fingerprint,
                output_path,
                preservation_required=True,
            )
    return {
        "output_path": output_path,
        "duration_policy": duration_policy or "reject_mismatch",
        "preservation_proofs": [proof.model_dump(mode="json")],
    }
