"""Host media adapter for hash-bound sound loudness requests.

Byte/demo operations retain the standalone PCM contract. Request mode also
accepts decoder-supported audio/video containers, using the same EBU R128
meter, bounded process ownership and delivery evaluator as the PCM operation.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import tempfile

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.defaults import DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS, DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS
from kinocut_sound.limits import MAX_MIX_DURATION_SECONDS, MIN_LOUDNESS_MATERIAL_SECONDS
from kinocut_sound.public.loudness_request import _material, _receipt, inspect_loudness_async as _pcm_async
from kinocut_sound.qa._errors import QA_UNAVAILABLE, QaError, qa_error
from kinocut_sound.qa.loudness import evaluate_loudness
from kinocut_sound.qa.meter import (
    _version,
    measure_with_identity,
    measure_with_identity_async,
    measurement_args,
    parse_summary,
    validate_material,
)
from kinocut_sound.qa.meter_process import run_meter_async, run_meter_sync

from kinocut.engine_runtime_utils import _ffmpeg, _ffprobe
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffprobe_json
from kinocut.limits import FFPROBE_TIMEOUT


def _pcm(data: bytes) -> bool:
    try:
        validate_material(data)
        return True
    except QaError as exc:
        if exc.code != "qa_input_invalid":
            raise
        return False


def _require_media_signature(data: bytes) -> None:
    # Reject text playlists before FFprobe/FFmpeg can follow external resources.
    # Supported families: RIFF/AIFF, ISO BMFF, MPEG audio, FLAC, Ogg and Matroska.
    supported = (
        data[:4] in (b"RIFF", b"RF64", b"FORM", b"fLaC", b"OggS", b"\x1aE\xdf\xa3")
        or data[4:8] == b"ftyp"
        or data[:3] == b"ID3"
        or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)
    )
    if not supported:
        raise qa_error("unsupported loudness media container", "qa_input_invalid")


@contextmanager
def _encoded_input(data: bytes):
    _require_media_signature(data)
    try:
        with tempfile.TemporaryDirectory(prefix="kinocut-loudness-media-") as folder:
            path = Path(folder) / "source.media"
            path.write_bytes(data)
            yield path, _ffmpeg()
    except (OSError, MCPVideoError, TypeError, ValueError) as exc:
        raise qa_error("loudness media could not be decoded or probed", QA_UNAVAILABLE) from exc


def _prepare_encoded(path, raw, binary):
    audio = next((stream for stream in raw.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if audio is None:
        raise qa_error("loudness measurement requires an audio stream", "qa_unmeasurable")
    duration = float(audio.get("duration") or raw.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or not MIN_LOUDNESS_MATERIAL_SECONDS <= duration <= MAX_MIX_DURATION_SECONDS:
        raise qa_error("loudness media duration is outside supported limits", "qa_unmeasurable")
    args = measurement_args(binary, path)
    args[args.index("-i") : args.index("-i")] = ["-xerror", "-protocol_whitelist", "file,pipe"]
    args[args.index("-af") : args.index("-af")] = ["-map", "0:a:0", "-vn"]
    return args, audio


def _encoded_receipt(data, policy, audio, metrics, version):
    return {
        "artifact_kind": "sound_loudness_measurement",
        "schema_version": 2,
        "demo": False,
        "source_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "policy_hash": canonical_digest(policy.model_dump(mode="json")),
        "meter": "ffmpeg_ebur128_true_peak",
        "backend_version": version,
        "audio_codec": audio.get("codec_name"),
        "channel_count": audio.get("channels"),
        "sample_rate_hz": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        **asdict(evaluate_loudness(metrics, policy)),
    }


def inspect_request(*, request, project_root, wav_bytes=None, delivery=None):
    if request is None and project_root is None:
        raise qa_error("loudness request requires an explicit project root and source", "qa_input_invalid")
    data, policy, demo = _material(wav_bytes, request, project_root, delivery)
    if _pcm(data):
        return _receipt(data, policy, demo, measure_with_identity(data))
    with _encoded_input(data) as (path, binary):
        args, audio = _prepare_encoded(path, _run_ffprobe_json(str(path)), binary)
        version = _version(run_meter_sync([binary, "-version"], DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS))
        metrics = parse_summary(run_meter_sync(args, DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS))
    return _encoded_receipt(data, policy, audio, metrics, version)


async def inspect_loudness_async(*, request=None, project_root=None):
    if request is None and project_root is None:
        return await _pcm_async()
    data, policy, demo = _material(None, request, project_root, None)
    if _pcm(data):
        return _receipt(data, policy, demo, await measure_with_identity_async(data))
    with _encoded_input(data) as (path, binary):
        probe_args = [_ffprobe(), "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        raw = json.loads(await run_meter_async(probe_args, FFPROBE_TIMEOUT))
        args, audio = _prepare_encoded(path, raw, binary)
        version = _version(await run_meter_async([binary, "-version"], DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS))
        metrics = parse_summary(await run_meter_async(args, DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS))
    return _encoded_receipt(data, policy, audio, metrics, version)


def invoke_sound_operation(name, **kwargs):
    from kinocut_sound.public import invoke_sound_operation as standalone

    if name == "sound-qa-loudness" and ("request" in kwargs or "project_root" in kwargs):
        if set(kwargs) - {"request", "project_root", "wav_bytes", "delivery"}:
            raise qa_error("unsupported loudness arguments", "qa_input_invalid")
        return inspect_request(
            request=kwargs.pop("request", None), project_root=kwargs.pop("project_root", None), **kwargs
        )
    return standalone(name, **kwargs)
