"""Deterministic, privacy-safe receipt helpers for audio-bed renders."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .contracts.audio_bed import AudioBedInput, AudioBedParameters, AudioBedReceipt
from .defaults import DEFAULT_HASH_CHUNK_BYTES
from .ffmpeg_helpers import _validate_artifact_path
from .validation import AUDIO_BED_SAFE_DISPLAY_RE


def _file_sha256(path: str) -> str:
    """Compute ``sha256:<hex>`` over file bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(DEFAULT_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_display_name(path: str) -> str:
    """Return a bounded, privacy-safe basename for a receipt display."""
    base = os.path.basename(path)
    match = AUDIO_BED_SAFE_DISPLAY_RE.fullmatch(base)
    if not match:
        return "input"
    return match.group()[:128]


def _toolchain() -> tuple[tuple[str, str | None], ...]:
    """Return the bounded toolchain fingerprint for the receipt."""
    from .workflow._versions import ffmpeg_version, mcp_video_version

    return (
        ("mcp_video", mcp_video_version()),
        ("ffmpeg", ffmpeg_version()),
    )


def _build_receipt(
    *,
    voice_source: str,
    music_path: str,
    voice_content_sha256: str,
    music_content_sha256: str,
    output_path: str,
    voice_duration: float,
    bed_duration: float,
    output_duration: float,
    voice_has_audio: bool,
    music_has_audio: bool,
    loop: bool,
    loop_crossfade: float,
    fade_in: float,
    fade_out: float,
    target_lufs: float,
    music_volume: float,
    duck_threshold: float,
    duck_ratio: float,
    duck_attack: float,
    duck_release: float,
    warnings: tuple[str, ...],
) -> AudioBedReceipt:
    """Build the deterministic edit-receipt from verified render evidence."""
    voice_input = AudioBedInput(
        role="voice_source",
        content_sha256=voice_content_sha256,
        probed_duration_seconds=voice_duration,
        display_name=_safe_display_name(voice_source),
        has_audio_stream=voice_has_audio,
    )
    music_input = AudioBedInput(
        role="music_bed",
        content_sha256=music_content_sha256,
        probed_duration_seconds=bed_duration,
        display_name=_safe_display_name(music_path),
        has_audio_stream=music_has_audio,
    )
    params = AudioBedParameters(
        loop=loop,
        loop_crossfade_seconds=loop_crossfade,
        fade_in_seconds=fade_in,
        fade_out_seconds=fade_out,
        music_volume=music_volume,
        target_lufs=target_lufs,
        duck_threshold=duck_threshold,
        duck_ratio=duck_ratio,
        duck_attack_ms=duck_attack,
        duck_release_ms=duck_release,
    )
    receipt = AudioBedReceipt(
        inputs=(voice_input, music_input),
        parameters=params,
        output_content_sha256=_file_sha256(output_path),
        output_duration_seconds=output_duration,
        output_display_name=_safe_display_name(output_path),
        ducking_engaged=voice_has_audio,
        warnings=warnings,
        toolchain=_toolchain(),
    )
    return receipt.model_copy(update={"receipt_sha256": _receipt_hash(receipt)})


def _receipt_hash(receipt: AudioBedReceipt) -> str:
    """Hash stable operation identity while excluding output-specific render fields."""
    payload = receipt.model_dump(
        mode="json",
        exclude={"receipt_sha256", "output_content_sha256", "output_duration_seconds"},
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write_receipt(path: str, receipt: AudioBedReceipt) -> None:
    """Write the receipt as pretty-printed JSON via an atomic temp-and-rename."""
    validated = _validate_artifact_path(path)
    temporary = Path(validated).with_name(f".{Path(validated).name}.{uuid.uuid4().hex}.tmp")
    payload = receipt.model_dump_json(indent=2)
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.replace(temporary, validated)
