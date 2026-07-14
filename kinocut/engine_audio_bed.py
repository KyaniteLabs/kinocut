"""Governed one-shot audio-bed primitive.

Composes the existing sidechain-ducking engine (``duck_audio`` heritage) with
loop/crossfade, fade-in/fade-out, EBU R128 loudness normalization, exact
output-duration policy (``keep_video``), deterministic edit-receipt, privacy-safe
project-relative identity, and cancellation-safe temp output.

Engine facade only — MCP/CLI/client registration is owned by the controller.
Imports shared helpers (never duplicates); every FFmpeg value is escaped; all
subprocess calls are bounded; custom errors only; fail-closed when sidechain
or loudnorm is unavailable; receipts carry only content hashes and safe basename
display names (absolute paths are structurally excluded by the contract).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from .audio_bed_validation import (
    reject_output_alias as _reject_output_alias,
    validate_audio_bed_params as _validate_audio_bed_params,
    validation_error as _validation_error,
)
from .contracts.audio_bed import AudioBedInput, AudioBedParameters, AudioBedReceipt
from .defaults import (
    DEFAULT_AUDIO_BED_DUCK_ATTACK_MS,
    DEFAULT_AUDIO_BED_DUCK_RATIO,
    DEFAULT_AUDIO_BED_DUCK_RELEASE_MS,
    DEFAULT_AUDIO_BED_DUCK_THRESHOLD,
    DEFAULT_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
    DEFAULT_HASH_CHUNK_BYTES,
    DEFAULT_AUDIO_BED_MUSIC_VOLUME,
    DEFAULT_AUDIO_BED_FADE_IN,
    DEFAULT_AUDIO_BED_FADE_OUT,
    DEFAULT_AUDIO_BED_LOOP_CROSSFADE,
    DEFAULT_AUDIO_BED_TARGET_LUFS,
    DEFAULT_AUDIO_BITRATE,
)
from .engine_runtime_utils import _check_filter_available, _movflags_args, _timed_operation
from .engine_audio_bed_filters import (
    _build_duck_filtergraph,
    _build_loop_filtergraph,
    _build_no_duck_filtergraph,
    _compute_loop_plays,
    _n,
)
from .errors import MCPVideoError, ProcessingError
from .ffmpeg_helpers import (
    _get_video_duration,
    _run_ffmpeg,
    _run_ffprobe_json,
    _validate_artifact_path,
    _validate_input_path,
    _validate_output_path,
)
from .source_identity import (
    VerifiedSource,
    copy_verified_snapshot,
    stream_source_identity,
)

from .validation import AUDIO_BED_SAFE_DISPLAY_RE

logger = logging.getLogger(__name__)


@contextmanager
def _verified_audio_sources(
    voice_source: str, music_path: str, output_path: str
) -> Iterator[tuple[VerifiedSource, VerifiedSource]]:
    """Yield immutable descriptors bound to the exact validated source bytes."""
    voice_identity = stream_source_identity(voice_source)
    music_identity = stream_source_identity(music_path)
    with ExitStack() as stack:
        workspace = stack.enter_context(
            tempfile.TemporaryDirectory(dir=Path(output_path).parent, prefix=".audio-bed.sources.")
        )
        root = Path(workspace)
        voice = copy_verified_snapshot(voice_source, root / "voice-source", voice_identity)
        stack.callback(voice.close)
        music = copy_verified_snapshot(music_path, root / "music-source", music_identity)
        stack.callback(music.close)
        yield voice, music


# ---------------------------------------------------------------------------
# Probing helpers
# ---------------------------------------------------------------------------


def _has_video_stream(path: str, *, pass_fds: tuple[int, ...] = ()) -> bool:
    data = _run_ffprobe_json(path, pass_fds=pass_fds)
    return any(s.get("codec_type") == "video" for s in data.get("streams", []))


def _has_audio_stream(path: str, *, pass_fds: tuple[int, ...] = ()) -> bool:
    data = _run_ffprobe_json(path, pass_fds=pass_fds)
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def _probe_duration(path: str, *, pass_fds: tuple[int, ...] = ()) -> float:
    """Probe a media file's duration using the shared ffprobe helper."""
    try:
        return _get_video_duration(path, pass_fds=pass_fds)
    except (ProcessingError, MCPVideoError):
        raise _validation_error("could not probe source duration", "probe_failed") from None


# ---------------------------------------------------------------------------
# Hashing and receipt helpers
# ---------------------------------------------------------------------------


def _file_sha256(path: str) -> str:
    """Compute ``sha256:<hex>`` over file bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(DEFAULT_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_display_name(path: str) -> str:
    """Return a privacy-safe basename for receipt display.

    Strips directory components entirely and sanitizes to the bounded display
    name alphabet (alphanumerics, dot, underscore, hyphen). The receipt must
    never carry an absolute source path.
    """
    base = os.path.basename(path)
    match = AUDIO_BED_SAFE_DISPLAY_RE.fullmatch(base)
    if not match:
        return "input"
    return match.group()[:128]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_args(
    voice_source: str,
    bed_input: str,
    output: str,
    *,
    voice_has_audio: bool,
    voice_has_video: bool,
    target_duration: float,
    filter_complex: str,
    map_video: bool,
) -> list[str]:
    """Construct the final FFmpeg argument list for the duck/normalize render."""
    args: list[str] = ["-i", voice_source, "-i", bed_input]
    args.extend(["-filter_complex", filter_complex])
    if map_video and voice_has_video:
        args.extend(["-map", "0:v:0", "-map", "[aout]"])
    else:
        args.extend(["-map", "[aout]"])
    if map_video and voice_has_video:
        args.extend(["-c:v", "copy"])
    args.extend(["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE])
    args.extend(["-t", _n(target_duration, "target_duration")])
    args.extend([*_movflags_args(output), output])
    return args


def _prepare_looped_bed(
    music_path: str,
    bed_duration: float,
    target_duration: float,
    loop_crossfade: float,
    workspace: Path,
    pass_fds: tuple[int, ...] = (),
) -> str:
    """Generate a crossfaded seamless-loop bed in a cancellation-safe temp file."""
    filter_graph, plays = _build_loop_filtergraph(bed_duration, target_duration, loop_crossfade)
    looped_path = workspace / "looped_bed.wav"
    _run_ffmpeg(
        [
            "-stream_loop",
            "-1",
            "-i",
            music_path,
            "-filter_complex",
            filter_graph,
            "-map",
            "[out]",
            "-t",
            _n(target_duration, "target_duration"),
            "-c:a",
            "pcm_s16le",
            str(looped_path),
        ],
        pass_fds=pass_fds,
    )
    logger.debug("audio_bed: looped bed with %d plays -> %s", plays, looped_path)
    return str(looped_path)


def _select_filtergraph(
    *,
    voice_has_audio: bool,
    bed_duration: float,
    target_duration: float,
    music_volume: float,
    duck_threshold: float,
    duck_ratio: float,
    duck_attack: float,
    duck_release: float,
    fade_in: float,
    fade_out: float,
    target_lufs: float,
    loop: bool,
    loop_crossfade: float,
) -> str:
    """Choose and build the duck or no-duck filtergraph for the render pass."""
    if voice_has_audio:
        return _build_duck_filtergraph(
            music_volume=music_volume,
            duck_threshold=duck_threshold,
            duck_ratio=duck_ratio,
            duck_attack=duck_attack,
            duck_release=duck_release,
            fade_in=fade_in,
            fade_out=fade_out,
            target_duration=target_duration,
            target_lufs=target_lufs,
        )
    needs_pad = bed_duration < target_duration and not (loop and loop_crossfade > 0)
    return _build_no_duck_filtergraph(
        music_volume=music_volume,
        fade_in=fade_in,
        fade_out=fade_out,
        target_duration=target_duration,
        target_lufs=target_lufs,
        needs_pad=needs_pad,
    )


def _guarded_render(
    voice_source: str,
    music_path: str,
    output_path: str,
    *,
    voice_has_audio: bool,
    voice_has_video: bool,
    target_duration: float,
    music_volume: float,
    duck_threshold: float,
    duck_ratio: float,
    duck_attack: float,
    duck_release: float,
    fade_in: float,
    fade_out: float,
    target_lufs: float,
    loop: bool,
    loop_crossfade: float,
    bed_duration: float,
    pass_fds: tuple[int, ...] = (),
) -> str:
    """Render to a staging file in the output dir, then atomically publish.

    Writes the final output into a private staging path in the same directory
    as ``output_path``, then ``os.replace`` moves it into place. On any error
    the staging file and workspace are cleaned up so no partial output remains.
    """
    parent = Path(output_path).parent
    staging_fd, staging_name = tempfile.mkstemp(
        dir=parent,
        prefix=".audio-bed.publish.",
        suffix=Path(output_path).suffix,
    )
    os.close(staging_fd)
    staging = Path(staging_name)
    try:
        with tempfile.TemporaryDirectory(dir=parent, prefix=".audio-bed.") as workspace_dir:
            workspace = Path(workspace_dir)
            bed_input = _resolve_bed_input(
                music_path,
                bed_duration,
                target_duration,
                loop,
                loop_crossfade,
                workspace,
                pass_fds=pass_fds,
            )
            fc = _select_filtergraph(
                voice_has_audio=voice_has_audio,
                bed_duration=bed_duration,
                target_duration=target_duration,
                music_volume=music_volume,
                duck_threshold=duck_threshold,
                duck_ratio=duck_ratio,
                duck_attack=duck_attack,
                duck_release=duck_release,
                fade_in=fade_in,
                fade_out=fade_out,
                target_lufs=target_lufs,
                loop=loop,
                loop_crossfade=loop_crossfade,
            )
            args = _render_args(
                voice_source,
                bed_input,
                str(staging),
                voice_has_audio=voice_has_audio,
                voice_has_video=voice_has_video,
                target_duration=target_duration,
                filter_complex=fc,
                map_video=True,
            )
            _run_ffmpeg(args, pass_fds=pass_fds)
        os.replace(staging, output_path)
        return output_path
    except BaseException:
        with suppress(OSError):
            staging.unlink(missing_ok=True)
        raise


def _resolve_bed_input(
    music_path: str,
    bed_duration: float,
    target_duration: float,
    loop: bool,
    loop_crossfade: float,
    workspace: Path,
    pass_fds: tuple[int, ...] = (),
) -> str:
    """Return the bed path to use: looped if needed, otherwise the original."""
    if loop and bed_duration < target_duration and loop_crossfade > 0:
        return _prepare_looped_bed(
            music_path,
            bed_duration,
            target_duration,
            loop_crossfade,
            workspace,
            pass_fds=pass_fds,
        )
    return music_path


# ---------------------------------------------------------------------------
# Duration verification
# ---------------------------------------------------------------------------


def _verify_output_duration(
    output_path: str,
    target_duration: float,
    tolerance: float,
) -> float:
    """Probe the rendered output and fail closed if duration policy is violated."""
    actual = _get_video_duration(output_path)
    if abs(actual - target_duration) > tolerance:
        raise ProcessingError(
            "audio_bed duration verification",
            0,
            f"output duration {actual:.3f}s deviates from keep_video policy "
            f"target {target_duration:.3f}s beyond tolerance {tolerance:.3f}s",
        )
    return actual


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


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
    """Deterministic sha256 over operation identity (inputs + parameters).

    Excludes the derived hash itself plus output-specific result fields whose
    values vary across renders (AAC encoding is not byte-deterministic). The
    output is still verifiable via ``output_content_sha256`` independently.
    """
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


# ---------------------------------------------------------------------------
# Public engine facade
# ---------------------------------------------------------------------------


class _BedProbe:
    """Probe result bundle for the two audio-bed sources."""

    __slots__ = (
        "bed_duration",
        "music_has_audio",
        "voice_duration",
        "voice_has_audio",
        "voice_has_video",
    )

    def __init__(
        self,
        voice_duration: float,
        bed_duration: float,
        voice_has_audio: bool,
        voice_has_video: bool,
        music_has_audio: bool,
    ):
        self.voice_duration = voice_duration
        self.bed_duration = bed_duration
        self.voice_has_audio = voice_has_audio
        self.voice_has_video = voice_has_video
        self.music_has_audio = music_has_audio


def _probe_sources(voice_source: str, music_path: str, *, pass_fds: tuple[int, ...] = ()) -> _BedProbe:
    """Probe durations and stream topology for both audio-bed sources."""
    return _BedProbe(
        voice_duration=_probe_duration(voice_source, pass_fds=pass_fds),
        bed_duration=_probe_duration(music_path, pass_fds=pass_fds),
        voice_has_audio=_has_audio_stream(voice_source, pass_fds=pass_fds),
        voice_has_video=_has_video_stream(voice_source, pass_fds=pass_fds),
        music_has_audio=_has_audio_stream(music_path, pass_fds=pass_fds),
    )


def _require_filters(voice_has_audio: bool) -> None:
    """Fail closed if the sidechain or loudnorm filters are unavailable."""
    if voice_has_audio and not _check_filter_available("sidechaincompress"):
        raise MCPVideoError(
            "sidechaincompress filter is unavailable; audio_bed refuses to silently substitute the simpler mixer.",
            error_type="dependency_error",
            code="missing_filter_sidechaincompress",
        )
    if not _check_filter_available("loudnorm"):
        raise MCPVideoError(
            "loudnorm filter is unavailable; audio_bed requires loudness normalization.",
            error_type="dependency_error",
            code="missing_filter_loudnorm",
        )


def _compute_warnings(
    *,
    voice_has_audio: bool,
    bed_duration: float,
    target_duration: float,
    loop: bool,
) -> list[str]:
    """Collect non-fatal warning codes for the receipt."""
    warnings: list[str] = []
    if not voice_has_audio:
        warnings.append("voice_source_has_no_audio")
        warnings.append("ducking_skipped")
    if bed_duration < target_duration and not loop:
        warnings.append("bed_shorter_than_voice_loop_disabled")
    return warnings


def _validate_loop_bounds(
    bed_duration: float,
    target_duration: float,
    loop: bool,
    loop_crossfade: float,
) -> bool:
    """Validate loop parameters and return whether looping is actually needed."""
    needs_loop = loop and bed_duration < target_duration and loop_crossfade > 0
    if needs_loop:
        if loop_crossfade >= bed_duration:
            raise _validation_error(
                "loop_crossfade must be smaller than the bed duration",
                "invalid_loop_crossfade",
            )
        _compute_loop_plays(bed_duration, target_duration, loop_crossfade)
    return needs_loop


def _finalize_audio_bed(
    *,
    voice_source: str, music_path: str, voice_display_path: str,
    music_display_path: str, voice_content_sha256: str, music_content_sha256: str,
    pass_fds: tuple[int, ...], output_path: str, probe: _BedProbe,
    target_duration: float, music_volume: float, duck_threshold: float,
    duck_ratio: float, duck_attack: float, duck_release: float,
    fade_in: float, fade_out: float, target_lufs: float,
    loop: bool, loop_crossfade: float, duration_tolerance: float,
    save_receipt: str | None, warnings: list[str], needs_loop: bool,
) -> dict[str, Any]:
    """Render, verify, build receipt, and return the structured result."""
    with _timed_operation() as timing:
        _guarded_render(
            voice_source,
            music_path,
            output_path,
            voice_has_audio=probe.voice_has_audio,
            voice_has_video=probe.voice_has_video,
            target_duration=target_duration,
            music_volume=music_volume,
            duck_threshold=duck_threshold,
            duck_ratio=duck_ratio,
            duck_attack=duck_attack,
            duck_release=duck_release,
            fade_in=fade_in,
            fade_out=fade_out,
            target_lufs=target_lufs,
            loop=loop,
            loop_crossfade=loop_crossfade,
            bed_duration=probe.bed_duration,
            pass_fds=pass_fds,
        )
    try:
        output_duration = _verify_output_duration(
            output_path,
            target_duration,
            duration_tolerance,
        )
    except ProcessingError:
        with suppress(OSError):
            Path(output_path).unlink(missing_ok=True)
        raise
    receipt = _build_receipt(
        voice_source=voice_display_path,
        music_path=music_display_path,
        voice_content_sha256=voice_content_sha256,
        music_content_sha256=music_content_sha256,
        output_path=output_path,
        voice_duration=probe.voice_duration,
        bed_duration=probe.bed_duration,
        output_duration=output_duration,
        voice_has_audio=probe.voice_has_audio,
        music_has_audio=probe.music_has_audio,
        music_volume=music_volume,
        loop=loop,
        loop_crossfade=loop_crossfade,
        fade_in=fade_in,
        fade_out=fade_out,
        target_lufs=target_lufs,
        duck_threshold=duck_threshold,
        duck_ratio=duck_ratio,
        duck_attack=duck_attack,
        duck_release=duck_release,
        warnings=tuple(warnings),
    )
    if save_receipt is not None:
        _write_receipt(save_receipt, receipt)
    logger.info(
        "audio_bed: rendered %s (%.3fs, ducking=%s, loop=%s) in %.0fms",
        output_path,
        output_duration,
        probe.voice_has_audio,
        needs_loop,
        timing.get("elapsed_ms") or 0.0,
    )
    return {"output_path": output_path, "output_duration": output_duration,
            "ducking_engaged": probe.voice_has_audio, "warnings": tuple(warnings),
            "elapsed_ms": timing.get("elapsed_ms"), "receipt": receipt.model_dump(mode="json")}


def audio_bed(
    voice_source: str, music_path: str, output_path: str,
    *,
    loop: bool = True, loop_crossfade: float = DEFAULT_AUDIO_BED_LOOP_CROSSFADE,
    fade_in: float = DEFAULT_AUDIO_BED_FADE_IN, fade_out: float = DEFAULT_AUDIO_BED_FADE_OUT,
    target_lufs: float = DEFAULT_AUDIO_BED_TARGET_LUFS,
    duck_threshold: float = DEFAULT_AUDIO_BED_DUCK_THRESHOLD, duck_ratio: float = DEFAULT_AUDIO_BED_DUCK_RATIO,
    duck_attack: float = DEFAULT_AUDIO_BED_DUCK_ATTACK_MS, duck_release: float = DEFAULT_AUDIO_BED_DUCK_RELEASE_MS,
    music_volume: float = DEFAULT_AUDIO_BED_MUSIC_VOLUME,
    duration_tolerance: float = DEFAULT_AUDIO_BED_DURATION_TOLERANCE_SECONDS, save_receipt: str | None = None,
) -> dict[str, Any]:
    """Governed one-shot audio-bed: duck music under voice, normalize, receipt."""
    _validate_audio_bed_params(
        loop=loop,
        loop_crossfade=loop_crossfade,
        fade_in=fade_in,
        fade_out=fade_out,
        target_lufs=target_lufs,
        duck_threshold=duck_threshold,
        duck_ratio=duck_ratio,
        duck_attack=duck_attack,
        duck_release=duck_release,
        music_volume=music_volume,
        duration_tolerance=duration_tolerance,
    )
    voice_source = _validate_input_path(voice_source)
    music_path = _validate_input_path(music_path)
    _validate_output_path(output_path)
    _reject_output_alias(output_path, (voice_source, music_path))
    if save_receipt is not None:
        _validate_artifact_path(save_receipt)
    with _verified_audio_sources(voice_source, music_path, output_path) as sources:
        voice_snapshot, music_snapshot = sources
        pass_fds = voice_snapshot.pass_fds + music_snapshot.pass_fds
        probe = _probe_sources(voice_snapshot.path, music_snapshot.path, pass_fds=pass_fds)
        if not probe.music_has_audio:
            raise _validation_error(
                "music bed must contain an audio stream",
                "missing_audio_stream",
            )
        _require_filters(probe.voice_has_audio)
        target_duration = probe.voice_duration
        needs_loop = _validate_loop_bounds(
            probe.bed_duration,
            target_duration,
            loop,
            loop_crossfade,
        )
        warnings = _compute_warnings(
            voice_has_audio=probe.voice_has_audio,
            bed_duration=probe.bed_duration,
            target_duration=target_duration,
            loop=loop,
        )
        return _finalize_audio_bed(
            voice_source=voice_snapshot.path,
            music_path=music_snapshot.path,
            voice_display_path=voice_source,
            music_display_path=music_path,
            voice_content_sha256=voice_snapshot.identity.asset_id,
            music_content_sha256=music_snapshot.identity.asset_id,
            pass_fds=pass_fds,
            output_path=output_path,
            probe=probe,
            target_duration=target_duration,
            music_volume=music_volume,
            duck_threshold=duck_threshold,
            duck_ratio=duck_ratio,
            duck_attack=duck_attack,
            duck_release=duck_release,
            fade_in=fade_in,
            fade_out=fade_out,
            target_lufs=target_lufs,
            loop=loop,
            loop_crossfade=loop_crossfade,
            duration_tolerance=duration_tolerance,
            save_receipt=save_receipt,
            warnings=warnings,
            needs_loop=needs_loop,
        )
