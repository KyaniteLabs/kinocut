"""Parent-owned sequential conversion into a private derived source root."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
import hashlib
import os
from tempfile import TemporaryDirectory, TemporaryFile

from kinocut_sound._errors import SoundContractError
from kinocut_sound.defaults import DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS
from kinocut_sound.limits import MAX_MIX_INPUT_BYTES
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.mix_conversion_backend import _convert_sync, _convert_async, _resolve_backend
from kinocut_sound.public.mix_conversion_shape import ConversionAdmission, ConversionShape, conversion_shape
from kinocut_sound.public.mix_conversion_manifest import (
    ConversionMedia,
    ConversionEntry,
    ConversionManifest,
    _roles,
    _backend_evidence,
    _validate_manifest,
    _manifest_bytes,
)
from kinocut_sound.public.mix_files import open_root, read_asset
from kinocut_sound.public.mix_process import remaining, run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async
from kinocut_sound.qa.meter import _version


@dataclass(frozen=True)
class PlannedConversion:
    ordinal: int
    kind: str
    binding_id: str
    asset_ref: str | None
    original: ConversionMedia
    shape: ConversionShape


@dataclass(frozen=True)
class PreparedConversion:
    root_fd: int
    manifest_fd: int
    manifest: ConversionManifest
    plans: tuple[PlannedConversion, ...]


def _source_plans(request, root_fd, deadline):
    admission = ConversionAdmission(request)
    for ordinal, (kind, binding_id, asset_ref, source) in enumerate(_roles(request)):
        remaining(deadline)
        data = read_asset(root_fd, source.path, source.sha256, MAX_MIX_INPUT_BYTES - admission.original_total)
        pcm, rate, channels = decode_pcm_wav(data)
        if channels != request.plan.format.channel_count:
            raise mix_error("rate conversion cannot change channel layout", "mix_unsupported_intent")
        shape = conversion_shape(len(pcm) // channels, rate, request.plan.format.sample_rate_hz, channels)
        admission.add(len(data), shape)
        original = ConversionMedia(
            path=source.path,
            sha256=source.sha256,
            sample_rate_hz=rate,
            frame_count=shape.source_frames,
            channel_count=channels,
            byte_count=len(data),
        )
        del pcm, data
        remaining(deadline)
        yield PlannedConversion(ordinal, kind, binding_id, asset_ref, original, shape)


def _entry(plan, digest, raw_frames, backend, request):
    shape = plan.shape
    derived = ConversionMedia(
        path=f"source_{plan.ordinal:04d}.wav",
        sha256=digest,
        sample_rate_hz=shape.target_rate,
        frame_count=shape.target_frames,
        channel_count=shape.channels,
        byte_count=shape.derived_bytes(plan.original.byte_count),
    )
    return ConversionEntry(
        kind=plan.kind,
        binding_id=plan.binding_id,
        asset_ref=plan.asset_ref,
        original=plan.original,
        derived=derived,
        profile=request.source_resampling.profile,
        mode="resample" if shape.changed else "copy",
        backend=backend if shape.changed else None,
        guard_frames=shape.guard_frames,
        raw_frames=raw_frames,
        discarded_frames=raw_frames - shape.target_frames,
    )


def _manifest_size_preflight(request, plans, backend):
    # Fixed-width hashes and maximum raw counts bound encoding BEFORE media jobs.
    # Templates are discarded here; only actual derived hashes enter the manifest.
    entries = tuple(
        _entry(
            plan,
            "sha256:" + "0" * 64 if plan.shape.changed else plan.original.sha256,
            plan.shape.raw_max,
            backend,
            request,
        )
        for plan in plans
    )
    _manifest_bytes(ConversionManifest(private_schema_version=1, request_hash=request.canonical_id(), entries=entries))


def _write_owned(root_fd, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
    with os.fdopen(fd, "wb") as output:
        if output.write(data) != len(data):
            raise mix_error("conversion staging returned a short write", "mix_conversion_failed")
        output.flush()
        os.fsync(output.fileno())


def _backend_result(code, output):
    if code:
        raise mix_error("conversion backend version probe failed", "mix_conversion_unavailable")
    try:
        return _backend_evidence(_version(output))
    except SoundContractError as exc:
        raise mix_error("conversion backend version is invalid", "mix_conversion_failed") from exc


def _store_audio(request, plan, audio, backend, root_fd):
    digest = "sha256:" + hashlib.sha256(audio.wav_bytes).hexdigest()
    entry = _entry(plan, digest, audio.raw_frames, backend, request)
    if len(audio.wav_bytes) != entry.derived.byte_count:
        raise mix_error("derived WAV byte count mismatch", "mix_conversion_failed")
    _write_owned(root_fd, entry.derived.path, audio.wav_bytes)
    return entry


def _finish_manifest(request, entries, root_fd):
    manifest = _validate_manifest(
        ConversionManifest(
            private_schema_version=1,
            request_hash=request.canonical_id(),
            entries=tuple(entries),
        ),
        request,
    )
    _write_owned(root_fd, "manifest.json", _manifest_bytes(manifest))
    fd = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    return manifest, fd


@contextmanager
def _prepared_assets(request, original_root, deadline):
    plans = tuple(_source_plans(request, original_root, deadline))
    binary = _resolve_backend() if any(plan.shape.changed for plan in plans) else None
    backend = None
    if binary is not None:
        backend = _backend_result(
            *run_worker_sync(
                [binary, "-version"],
                b"",
                (),
                min(remaining(deadline), DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS),
            )
        )
    _manifest_size_preflight(request, plans, backend)
    with TemporaryDirectory(prefix="kinocut-conversion-") as directory, open_root(directory) as root_fd:
        entries = []
        for plan in plans:
            remaining(deadline)
            data = read_asset(original_root, plan.original.path, plan.original.sha256, MAX_MIX_INPUT_BYTES)
            with TemporaryFile(dir=directory) as raw:
                audio = _convert_sync(data, plan.shape, raw, binary, deadline)
                entries.append(_store_audio(request, plan, audio, backend, root_fd))
            del data, audio
        manifest, fd = _finish_manifest(request, entries, root_fd)
        try:
            yield PreparedConversion(root_fd, fd, manifest, plans)
        finally:
            os.close(fd)


@asynccontextmanager
async def _prepared_assets_async(request, original_root, deadline):
    plans = []
    for plan in _source_plans(request, original_root, deadline):
        plans.append(plan)
        await asyncio.sleep(0)
    binary = _resolve_backend() if any(plan.shape.changed for plan in plans) else None
    backend = None
    if binary is not None:
        backend = _backend_result(
            *await run_worker_async(
                [binary, "-version"],
                b"",
                (),
                min(remaining(deadline), DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS),
            )
        )
    _manifest_size_preflight(request, plans, backend)
    with TemporaryDirectory(prefix="kinocut-conversion-") as directory, open_root(directory) as root_fd:
        entries = []
        for plan in plans:
            remaining(deadline)
            data = read_asset(original_root, plan.original.path, plan.original.sha256, MAX_MIX_INPUT_BYTES)
            with TemporaryFile(dir=directory) as raw:
                audio = await _convert_async(data, plan.shape, raw, binary, deadline)
                entries.append(_store_audio(request, plan, audio, backend, root_fd))
            del data, audio
            await asyncio.sleep(0)
        manifest, fd = _finish_manifest(request, entries, root_fd)
        try:
            yield PreparedConversion(root_fd, fd, manifest, tuple(plans))
        finally:
            os.close(fd)
