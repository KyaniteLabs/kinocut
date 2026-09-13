"""V4 private descriptor protocol and its separate public evidence projection."""

import json
import os
import stat
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound._errors import SoundContractError
from kinocut_sound.defaults import (
    DEFAULT_MIX_CONVERSION_THREADS,
    DEFAULT_MIX_CONVERSION_PRECISION,
    DEFAULT_MIX_CONVERSION_CUTOFF,
    DEFAULT_MIX_CONVERSION_CHEBY,
    DEFAULT_MIX_CONVERSION_DITHER_METHOD,
)
from kinocut_sound.limits import (
    MAX_ASSEMBLY_CLIPS,
    MAX_AMBIENT_LAYERS,
    MAX_MIX_INPUT_BYTES,
    MAX_MIX_CONVERSION_MANIFEST_BYTES,
    MIN_MIX_SAMPLE_RATE_HZ,
    MAX_MIX_SAMPLE_RATE_HZ,
)
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_conversion_shape import conversion_shape, check_conversion_resources
from kinocut_sound.public.mix_request import SourceAsset, _check_tree
from kinocut_sound.public.mix_request_v4 import ResamplingProfile
from kinocut_sound.public.mix_routing_receipt import bounded_json
from kinocut_sound.qa.meter import _version


class ConversionMedia(SourceAsset):
    sample_rate_hz: int = Field(strict=True, ge=MIN_MIX_SAMPLE_RATE_HZ, le=MAX_MIX_SAMPLE_RATE_HZ)
    frame_count: int = Field(strict=True, ge=1, le=MAX_MIX_INPUT_BYTES // 2)
    channel_count: int = Field(strict=True, ge=1, le=2)
    byte_count: int = Field(strict=True, ge=1, le=MAX_MIX_INPUT_BYTES)


class ConversionBackend(FrozenModel):
    id: Literal["ffmpeg"]
    version: str
    decoder_threads: int = Field(strict=True)
    filter_threads: int = Field(strict=True)
    precision: int = Field(strict=True)
    cutoff: float = Field(strict=True)
    cheby: bool = Field(strict=True)
    dither_method: int = Field(strict=True)

    @field_validator("version")
    @classmethod
    def _bounded_version(cls, value):
        if _version(("ffmpeg version " + value + "\n").encode()) != value:
            raise mix_error("invalid conversion backend version", "mix_worker_failed")
        return value


class ConversionEntry(FrozenModel):
    kind: Literal["clip", "bed", "layer"]
    binding_id: str
    asset_ref: str | None
    original: ConversionMedia
    derived: ConversionMedia
    profile: ResamplingProfile
    mode: Literal["copy", "resample"]
    backend: ConversionBackend | None
    guard_frames: int = Field(strict=True, ge=0)
    raw_frames: int = Field(strict=True, ge=1)
    discarded_frames: int = Field(strict=True, ge=0)

    _id = field_validator("binding_id")(BoundedCode)

    @field_validator("asset_ref")
    @classmethod
    def _asset(cls, value):
        return BoundedCode(value) if value is not None else None


class ConversionManifest(FrozenModel):
    private_schema_version: int = Field(strict=True, ge=1, le=1)
    request_hash: Sha256
    entries: tuple[ConversionEntry, ...] = Field(max_length=MAX_ASSEMBLY_CLIPS + MAX_AMBIENT_LAYERS + 1)


def _roles(request):
    for clip in request.clips:
        yield "clip", clip.cue_id, None, clip
    if request.bed:
        yield "bed", "bed", None, request.bed
    for item in request.layer_assets:
        yield "layer", item.layer.layer_id, item.layer.asset_ref, item.source


def _backend_evidence(version):
    return ConversionBackend(
        id="ffmpeg",
        version=version,
        decoder_threads=DEFAULT_MIX_CONVERSION_THREADS,
        filter_threads=DEFAULT_MIX_CONVERSION_THREADS,
        precision=DEFAULT_MIX_CONVERSION_PRECISION,
        cutoff=DEFAULT_MIX_CONVERSION_CUTOFF,
        cheby=DEFAULT_MIX_CONVERSION_CHEBY,
        dither_method=DEFAULT_MIX_CONVERSION_DITHER_METHOD,
    )


def _validate_entry(entry, role, ordinal, request):
    kind, binding_id, asset_ref, source = role
    if (entry.kind, entry.binding_id, entry.asset_ref) != (kind, binding_id, asset_ref):
        raise mix_error("conversion role identities mismatch", "mix_worker_failed")
    if (entry.original.path, entry.original.sha256) != (source.path, source.sha256):
        raise mix_error("conversion original binding mismatch", "mix_worker_failed")
    if entry.derived.path != f"source_{ordinal:04d}.wav" or entry.profile != request.source_resampling.profile:
        raise mix_error("conversion private name or profile mismatch", "mix_worker_failed")
    original, derived = entry.original, entry.derived
    shape = conversion_shape(
        original.frame_count, original.sample_rate_hz, request.plan.format.sample_rate_hz, original.channel_count
    )
    if original.channel_count != request.plan.format.channel_count or (
        derived.sample_rate_hz,
        derived.channel_count,
        derived.frame_count,
        derived.byte_count,
    ) != (shape.target_rate, shape.channels, shape.target_frames, shape.derived_bytes(original.byte_count)):
        raise mix_error("conversion target shape mismatch", "mix_worker_failed")
    if entry.guard_frames != shape.guard_frames or entry.raw_frames not in (shape.raw_min, shape.raw_max):
        raise mix_error("conversion raw frame envelope mismatch", "mix_worker_failed")
    if entry.raw_frames < shape.target_frames or entry.discarded_frames != entry.raw_frames - shape.target_frames:
        raise mix_error("conversion discarded frame count mismatch", "mix_worker_failed")
    if shape.changed:
        if (
            entry.mode != "resample"
            or entry.backend is None
            or entry.backend != _backend_evidence(entry.backend.version)
        ):
            raise mix_error("conversion backend profile mismatch", "mix_worker_failed")
    elif entry.mode != "copy" or entry.backend is not None or original.sha256 != derived.sha256:
        raise mix_error("same-rate conversion must be byte-identical", "mix_worker_failed")
    return original.byte_count, shape


def _validate_manifest(manifest, request):
    if request.schema_version != 4 or manifest.request_hash != request.canonical_id():
        raise mix_error("conversion manifest request identity mismatch", "mix_worker_failed")
    roles = tuple(_roles(request))
    if len(roles) != len(manifest.entries):
        raise mix_error("conversion manifest binding count mismatch", "mix_worker_failed")
    shapes = [
        _validate_entry(entry, role, i, request)
        for i, (entry, role) in enumerate(zip(manifest.entries, roles, strict=True))
    ]
    check_conversion_resources(request, shapes)
    return manifest


def _manifest_bytes(manifest):
    return bounded_json(manifest.model_dump(mode="json"), MAX_MIX_CONVERSION_MANIFEST_BYTES)


def _load_manifest_fd(fd, request):
    try:
        import fcntl

        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
            raise mix_error("conversion manifest descriptor must be read-only", "mix_worker_failed")
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MIX_CONVERSION_MANIFEST_BYTES:
            raise mix_error("conversion manifest is not a bounded regular file", "mix_worker_failed")
        raw = os.pread(fd, MAX_MIX_CONVERSION_MANIFEST_BYTES + 1, 0)
        after = os.fstat(fd)
        markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) != before.st_size or any(getattr(before, key) != getattr(after, key) for key in markers):
            raise mix_error("conversion manifest changed while reading", "mix_worker_failed")
        value = json.loads(raw)
        _check_tree(value)
        return _validate_manifest(ConversionManifest.model_validate(value), request)
    except (OSError, ValueError, TypeError, RecursionError, ValidationError, SoundContractError) as exc:
        raise mix_error("invalid private conversion manifest", "mix_worker_failed") from exc


def _public_projection(manifest, request):
    entries = []
    for entry in manifest.entries:
        value = entry.model_dump(mode="json")
        value["derived"].pop("path")
        entries.append(value)
    result = {"profile": request.source_resampling.profile.value, "entries": entries}
    bounded_json(result, MAX_MIX_CONVERSION_MANIFEST_BYTES)
    return result
