"""Merge operations for the FFmpeg engine."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import warnings as _warnings

from .defaults import (
    DEFAULT_AUDIO_CHANNELS,
    DEFAULT_CRF,
    DEFAULT_FPS,
    DEFAULT_PRESET,
    DEFAULT_SAMPLE_RATE,
)
from .engine_probe import get_duration, probe
from .engine_runtime_utils import _build_edit_result, _movflags_args, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _build_ffmpeg_cmd, _run_ffmpeg
from .errors import InputFileError, MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _validate_input_path, _validate_output_path
from .merge_guardrails import validate_merge_compatibility
from .models import EditResult
from .validation import VALID_XFADE_TRANSITIONS

logger = logging.getLogger(__name__)


def _normalize_clips(
    clips: list[str],
    infos: list,
    target_w: int,
    target_h: int,
    tmpdir: str,
) -> list[str]:
    """Normalize clips to common resolution, codec, fps, and audio rate.

    Returns list of normalized clip paths inside *tmpdir*.
    """
    working: list[str] = []
    for i, clip in enumerate(clips):
        norm_path = os.path.join(tmpdir, f"clip_{i:04d}.mp4")
        info = infos[i]
        vf_parts = [
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2",
        ]
        if info.rotation == 90:
            vf_parts.insert(0, "transpose=2")
        elif info.rotation == 270:
            vf_parts.insert(0, "transpose=1")
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                clip,
                output_path=norm_path,
                video_filter=",".join(vf_parts),
                crf=DEFAULT_CRF,
                preset=DEFAULT_PRESET,
                extra=[
                    "-r",
                    str(DEFAULT_FPS),
                    "-ar",
                    str(DEFAULT_SAMPLE_RATE),
                    "-ac",
                    str(DEFAULT_AUDIO_CHANNELS),
                ],
            )
        )
        working.append(norm_path)
    return working


def _merge_single_clip(clip: str, output_path: str | None) -> EditResult:
    """Fast path for single-clip merge: copy or remux to output."""
    output = output_path or _auto_output(clip, "merged")
    _validate_output_path(output)
    input_ext = os.path.splitext(clip)[1].lower()
    output_ext = os.path.splitext(output)[1].lower()
    if output_path is not None and input_ext != output_ext:
        _run_ffmpeg(["-i", clip, "-c", "copy", *_movflags_args(output), output])
    else:
        shutil.copy2(clip, output)
    return _build_edit_result(
        output,
        "merge",
        {"elapsed_ms": 0.0},
    )


def _concat_clips(clips: list[str], output: str, tmpdir: str) -> None:
    """Concatenate clips using FFmpeg concat demuxer."""
    concat_file = os.path.join(tmpdir, "concat.txt")
    with open(concat_file, "w") as f:
        for clip in clips:
            abs_path = os.path.abspath(clip).replace("\\", "\\\\").replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", *_movflags_args(output), output])


def merge(
    clips: list[str],
    output_path: str | None = None,
    transition: str | None = None,
    transitions: list[str] | None = None,
    transition_duration: float = 1.0,
) -> EditResult:
    """Merge multiple clips into one video. Auto-normalizes if needed.

    Args:
        clips: List of video file paths.
        output_path: Output file path.
        transition: Single transition type for all clip pairs (backward compat).
        transitions: Per-pair transition types (one per boundary, len = len(clips)-1).
            If shorter than clip pairs, the last type is repeated.
        transition_duration: Duration of each transition in seconds.
    """
    if not clips:
        raise InputFileError("", "No clips provided for merge")
    if len(clips) == 1:
        return _merge_single_clip(_validate_input_path(clips[0]), output_path)

    clips = [_validate_input_path(c) for c in clips]
    infos = [probe(c) for c in clips]

    # --- Guardrails: pre-merge compatibility ---
    has_transitions = bool(transition or transitions)
    try:
        merge_warnings = validate_merge_compatibility(
            infos,
            transition_duration=transition_duration if has_transitions else 0.0,
        )
        for w in merge_warnings:
            _warnings.warn(f"[MERGE GUARDRAIL] {w}", stacklevel=2)
    except MCPVideoError:
        raise
    except Exception as e:
        message = f"[MERGE GUARDRAIL] Could not validate merge compatibility: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=2)
    # --- End guardrails ---

    resolutions = {i.display_resolution for i in infos}
    codecs = {i.codec for i in infos}
    fps_set = {round(i.fps, 2) for i in infos}
    audio_rates = {i.audio_sample_rate for i in infos if i.audio_sample_rate}

    audio_flags = [i.audio_codec is not None for i in infos]
    # Mixed audio presence breaks both the concat demuxer and the xfade audio
    # graph (it would reference an [i:a] pad that does not exist).
    mixed_audio = any(audio_flags) and not all(audio_flags)

    needs_normalize = len(resolutions) > 1 or len(codecs) > 1 or len(fps_set) > 1 or len(audio_rates) > 1 or mixed_audio
    target_w = max(i.display_width for i in infos)
    target_h = max(i.display_height for i in infos)

    with _timed_operation() as timing:
        tmpdir = tempfile.mkdtemp(prefix="mcp_video_")
        try:
            source_clips = _add_silent_audio(clips, infos, tmpdir) if mixed_audio else list(clips)
            if needs_normalize:
                working_clips = _normalize_clips(source_clips, infos, target_w, target_h, tmpdir)
            else:
                working_clips = source_clips

            output = output_path or _auto_output(clips[0], "merged")
            _validate_output_path(output)

            transition_types: list[str] | None = None
            if transitions and len(working_clips) > 1:
                transition_types = list(transitions)
            elif transition and len(working_clips) > 1:
                transition_types = [transition] * (len(working_clips) - 1)

            if transition_types and len(working_clips) > 1:
                _merge_with_transitions(working_clips, output, transition_types, transition_duration)
            else:
                _concat_clips(working_clips, output, tmpdir)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return _build_edit_result(
        output,
        "merge",
        timing,
    )


def _add_silent_audio(clips: list[str], infos: list, tmpdir: str) -> list[str]:
    """Give audio-less clips a silent track so every clip has the same stream layout."""
    sample_rate = next((i.audio_sample_rate for i in infos if i.audio_sample_rate), DEFAULT_SAMPLE_RATE)
    working: list[str] = []
    for idx, (clip, info) in enumerate(zip(clips, infos, strict=True)):
        if info.audio_codec is not None:
            working.append(clip)
            continue
        silent_path = os.path.join(tmpdir, f"silent_{idx:04d}.mp4")
        _run_ffmpeg(
            [
                "-i",
                clip,
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={sample_rate}",
                "-shortest",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                silent_path,
            ]
        )
        working.append(silent_path)
    return working


def _merge_with_transitions(
    clips: list[str],
    output: str,
    transition_types: list[str],
    transition_duration: float,
) -> None:
    """Merge clips with xfade transitions between them.

    Args:
        transition_types: One transition type per clip pair (len = len(clips)-1).
            If shorter, the last type is repeated.
    """
    n = len(clips)
    if n < 2:
        _run_ffmpeg(["-i", clips[0], "-c", "copy", output])
        return

    # Pad transition_types if shorter than clip pairs
    pairs = n - 1
    if len(transition_types) < pairs:
        last = transition_types[-1] if transition_types else "fade"
        transition_types = transition_types + [last] * (pairs - len(transition_types))

    # xfade offset calculation
    offsets: list[float] = []
    cumulative = 0.0
    for i in range(pairs):
        clip_dur = get_duration(clips[i])
        if transition_duration >= clip_dur:
            raise MCPVideoError(
                f"Transition duration ({transition_duration}s) must be less than "
                f"clip {i + 1} duration ({clip_dur:.1f}s)",
                code="transition_too_long",
            )
        cumulative += clip_dur - transition_duration
        offsets.append(cumulative)

    # Build complex filter
    inputs = []
    for clip in clips:
        inputs.extend(["-i", clip])

    # Build filter chain with per-pair transition types
    filter_parts = []
    labels: list[str] = []
    for i in range(n):
        labels.append(f"{i}:v")

    for i in range(pairs):
        in1 = labels[i]
        in2 = labels[i + 1]
        out = f"xt{i}" if i < pairs - 1 else "vout"
        xfade_type = transition_types[i].replace("-", "")
        # Validate here too, not only at the MCP tool layer — the Python client
        # and CLI reach this engine directly with unchecked strings.
        if xfade_type not in VALID_XFADE_TRANSITIONS:
            raise MCPVideoError(
                f"Invalid transition '{transition_types[i]}'. "
                f"Must be one of: {', '.join(sorted(VALID_XFADE_TRANSITIONS))}",
                error_type="validation_error",
                code="invalid_transition",
            )
        safe_xfade = _escape_ffmpeg_filter_value(xfade_type)
        safe_offset = _escape_ffmpeg_filter_value(f"{offsets[i]:.3f}")
        safe_duration = _escape_ffmpeg_filter_value(f"{transition_duration:.3f}")
        filter_parts.append(
            f"[{in1}][{in2}]xfade=transition={safe_xfade}:offset={safe_offset}:duration={safe_duration}[{out}]"
        )
        labels[i + 1] = out

    filter_str = ";".join(filter_parts)

    # Audio: only include if clips have audio streams
    has_audio = any(probe(c).audio_codec is not None for c in clips)
    if has_audio:
        # Crossfade audio with acrossfade so it overlaps by the SAME duration the
        # video xfade overlaps. The old code concatenated audio at full length while
        # xfade shortened the video timeline by transition_duration per transition,
        # so audio ran longer than video and A/V drift accumulated with each cut.
        audio_labels = [f"{i}:a" for i in range(n)]
        audio_parts = []
        for i in range(pairs):
            a_out = f"at{i}" if i < pairs - 1 else "aout"
            audio_parts.append(
                f"[{audio_labels[i]}][{audio_labels[i + 1]}]acrossfade=d={transition_duration:.3f}[{a_out}]"
            )
            audio_labels[i + 1] = a_out
        audio_filter = ";".join(audio_parts)
        filter_complex = f"{filter_str};{audio_filter}"
        map_args = ["-map", "[vout]", "-map", "[aout]"]
    else:
        filter_complex = filter_str
        map_args = ["-map", "[vout]"]

    if has_audio:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                *clips,
                output_path=output,
                crf=DEFAULT_CRF,
                preset=DEFAULT_PRESET,
                extra=[
                    "-filter_complex",
                    filter_complex,
                    *map_args,
                ],
            )
        )
    else:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                *clips,
                output_path=output,
                audio_codec=None,
                crf=DEFAULT_CRF,
                preset=DEFAULT_PRESET,
                extra=[
                    "-an",
                    "-filter_complex",
                    filter_complex,
                    *map_args,
                ],
            )
        )
