"""Audio attachment operations for the FFmpeg engine."""

from __future__ import annotations

import logging
import warnings as _warnings

from .defaults import DEFAULT_AUDIO_BITRATE
from .engine_probe import probe, probe_audio_input
from .engine_runtime_utils import (
    _build_edit_result,
    _has_audio,
    _movflags_args,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value, _run_ffprobe_json
from .audio_guardrails import validate_audio_mix
from .errors import MCPVideoError
from .models import EditResult
from .validation import DURATION_POLICIES

logger = logging.getLogger(__name__)


def _build_audio_filters(volume: float, fade_in: float, fade_out: float, duration: float) -> list[str]:
    """Build audio filter strings for volume and fade effects."""
    filters: list[str] = []
    if volume != 1.0:
        filters.append(f"volume={_escape_ffmpeg_filter_value(str(volume))}")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={_escape_ffmpeg_filter_value(str(fade_in))}")
    if fade_out > 0:
        fade_start = max(0.0, duration - fade_out)
        filters.append(
            f"afade=t=out:st={_escape_ffmpeg_filter_value(str(fade_start))}:"
            f"d={_escape_ffmpeg_filter_value(str(fade_out))}"
        )
    return filters


def _build_add_audio_args(
    video_path: str,
    audio_path: str,
    filters: list[str],
    mix: bool,
    start_time: float | None,
    source_has_audio: bool,
    output: str,
    *,
    duration_policy: str = "keep_video",
    video_duration: float | None = None,
) -> list[str]:
    """Construct FFmpeg argument list for add_audio operation.

    ``duration_policy`` decides how the replaced audio is reconciled with the
    video length: every policy except ``shortest`` caps the output at the video's
    duration (``-t``) so the outro is preserved; ``pad_audio`` adds silence,
    ``loop_audio`` loops the audio input to fill, and ``shortest`` keeps the
    legacy ``-shortest``. In mix mode the source-preserving ``amix`` duration is
    ``longest`` (or ``shortest`` only under the explicit ``shortest`` policy).
    """

    if mix and source_has_audio:
        af = ",".join(filters) if filters else "anull"
        amix_duration = "shortest" if duration_policy == "shortest" else "longest"
        # Output tail: shortest genuinely cuts to the shortest input; every other
        # policy caps the mix at the video duration so a longer added track can
        # never stretch the output past the video.
        mix_tail = (
            ["-shortest"]
            if duration_policy == "shortest" or video_duration is None
            else ["-t", _escape_ffmpeg_filter_value(f"{float(video_duration):.6f}")]
        )
        # The added track is one chain: [1:a] -> optional adelay -> filters -> [a1].
        # Referencing [1:a] a second time mid-chain is invalid filtergraph syntax
        # even where some FFmpeg builds tolerate it.
        if start_time:
            safe_delay = _escape_ffmpeg_filter_value(str(int(start_time * 1000)))
            second_chain = f"[1:a]adelay={safe_delay}|{safe_delay},{af}[a1]"
        else:
            second_chain = f"[1:a]{af}[a1]"
        filter_complex = f"[0:a]anull[a0];{second_chain};[a0][a1]amix=inputs=2:duration={amix_duration}[aout]"
        return [
            "-i",
            video_path,
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            *mix_tail,
            *_movflags_args(output),
            output,
        ]

    # --- Replace audio (or add if no existing audio) ---
    # Duration control (replace path only, so loop/pad never feed an unbounded
    # stream into amix): non-shortest policies cap the output at the video length.
    loop_prefix = ["-stream_loop", "-1"] if duration_policy == "loop_audio" else []
    audio_filters = [*filters, "apad"] if duration_policy == "pad_audio" else list(filters)
    if duration_policy == "shortest" or video_duration is None:
        tail = ["-shortest"]
    else:
        tail = ["-t", _escape_ffmpeg_filter_value(f"{float(video_duration):.6f}")]

    args = ["-i", video_path, *loop_prefix, "-i", audio_path]
    if start_time:
        # adelay and the volume/fade filters must share a single filtergraph:
        # FFmpeg forbids combining -filter_complex and -af on the same output
        # stream, so fold the filters into the complex chain after the delay.
        safe_delay = _escape_ffmpeg_filter_value(str(int(start_time * 1000)))
        delay_chain = f"[1:a]adelay={safe_delay}|{safe_delay}"
        if audio_filters:
            delay_chain += "," + ",".join(audio_filters)
        delay_chain += "[a]"
        args.extend(["-filter_complex", delay_chain])
        args.extend(["-map", "0:v:0", "-map", "[a]"])
    else:
        args.extend(["-map", "0:v:0", "-map", "1:a:0"])
        if audio_filters:
            args.extend(["-af", ",".join(audio_filters)])

    args.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE, *tail, *_movflags_args(output), output])
    return args


def _validate_duration_policy(duration_policy: str, mix: bool) -> None:
    """Validate the duration policy without echoing hostile input into errors."""

    if duration_policy not in DURATION_POLICIES:
        # Never echo the raw (possibly hostile) value back into a public error.
        raise MCPVideoError(
            f"duration_policy must be one of {DURATION_POLICIES}",
            error_type="validation_error",
            code="invalid_duration_policy",
        )
    if mix and duration_policy in ("loop_audio", "pad_audio"):
        # Looping/padding an added track feeds an unbounded stream into ``amix``;
        # rather than hang or silently ignore the policy, fail closed.
        raise MCPVideoError(
            f"duration_policy={duration_policy!r} is not supported with mix=True; "
            "use keep_video, trim_audio, or shortest",
            error_type="validation_error",
            code="unsupported_duration_policy_for_mix",
        )


def _emit_add_audio_guardrails(video_info, audio_path: str, volume: float, start_time: float | None) -> None:
    """Emit volume/mix guardrail warnings (and the hard volume<0 error)."""

    if volume < 0.0:
        raise MCPVideoError(
            f"volume must be >= 0, got {volume}",
            error_type="validation_error",
            code="invalid_volume",
        )
    if volume > 1.0:
        _warnings.warn(
            f"[AUDIO GUARDRAIL] volume={volume} > 1.0. If source audio is already "
            f"near peak, this may cause digital clipping/distortion.",
            stacklevel=2,
        )
    # The attached audio is commonly an audio-only file (e.g. a voiceover WAV),
    # so probe it with an audio-aware probe — otherwise a valid WAV is misreported
    # as "No video stream found" (issue #7).
    try:
        audio_info = probe_audio_input(audio_path)
        mix_warnings = validate_audio_mix(video_info, audio_info, volume=volume, start_time=start_time or 0.0)
        for w in mix_warnings:
            _warnings.warn(f"[AUDIO GUARDRAIL] {w}", stacklevel=2)
    except Exception as e:
        message = f"[AUDIO GUARDRAIL] Could not validate audio mix: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=2)


def add_audio(
    video_path: str,
    audio_path: str,
    volume: float = 1.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    mix: bool = False,
    start_time: float | None = None,
    output_path: str | None = None,
    *,
    duration_policy: str = "keep_video",
) -> EditResult:
    """Add or replace audio track on a video.

    ``duration_policy`` (keyword-only, additive) controls how the audio length is
    reconciled with the video: ``keep_video`` (default) holds the full video
    duration; ``pad_audio`` pads short audio with silence; ``loop_audio`` loops
    it; ``trim_audio`` caps long audio; ``shortest`` reproduces the legacy
    ``-shortest`` behaviour (which can eat the outro) and appends a warning.
    """
    _validate_duration_policy(duration_policy, mix)
    video_path = _validate_input_path(video_path)
    audio_path = _validate_input_path(audio_path)
    output = output_path or _auto_output(video_path, "audio")
    _validate_output_path(output)

    video_info = probe(video_path)
    source_has_audio = _has_audio(_run_ffprobe_json(video_path))
    _emit_add_audio_guardrails(video_info, audio_path, volume, start_time)

    with _timed_operation() as timing:
        filters = _build_audio_filters(volume, fade_in, fade_out, video_info.duration)
        cmd = _build_add_audio_args(
            video_path,
            audio_path,
            filters,
            mix,
            start_time,
            source_has_audio,
            output,
            duration_policy=duration_policy,
            video_duration=video_info.duration,
        )
        _run_ffmpeg(cmd)

    warnings = []
    if source_has_audio and not mix:
        warnings.append(
            "This operation will replace existing audio. Use mix=True to "
            "preserve source audio and listen before publishing."
        )
    if duration_policy == "shortest":
        warnings.append(
            "duration_policy='shortest' may shorten the output below the source "
            "video duration (the outro can be trimmed). Use 'keep_video' to preserve it."
        )

    return _build_edit_result(output, "add_audio", timing).model_copy(update={"warnings": warnings})


def duck_audio(
    video_path: str,
    music_path: str,
    output_path: str | None = None,
    music_volume: float = 0.6,
    threshold: float = 0.05,
    ratio: float = 8.0,
    attack: float = 20.0,
    release: float = 300.0,
) -> EditResult:
    """Mix background music under a video's audio, auto-ducking it when the voice plays.

    Uses FFmpeg's sidechaincompress keyed by the video's own audio track, so the
    music dips during speech and recovers in pauses — the standard treatment for
    shorts, reels, and podcast clips.

    Args:
        video_path: Video whose existing audio (voice) drives the ducking.
        music_path: Background music or ambience to mix underneath.
        output_path: Where to save the result. Auto-generated if omitted.
        music_volume: Base music level before ducking (0-2, 1.0 = unchanged).
        threshold: Sidechain level above which ducking engages (0-1).
        ratio: Compression ratio applied to the music while voice plays (1-20).
        attack: How fast the music dips, in milliseconds (1-2000).
        release: How fast the music recovers, in milliseconds (1-9000).
    """
    video_path = _validate_input_path(video_path)
    music_path = _validate_input_path(music_path)
    output = output_path or _auto_output(video_path, "ducked")
    _validate_output_path(output)

    if not 0 < music_volume <= 2:
        raise MCPVideoError(
            f"music_volume must be in (0, 2], got {music_volume}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not 0 < threshold <= 1:
        raise MCPVideoError(
            f"threshold must be in (0, 1], got {threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not 1 <= ratio <= 20:
        raise MCPVideoError(
            f"ratio must be between 1 and 20, got {ratio}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not 1 <= attack <= 2000:
        raise MCPVideoError(
            f"attack must be between 1 and 2000 ms, got {attack}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not 1 <= release <= 9000:
        raise MCPVideoError(
            f"release must be between 1 and 9000 ms, got {release}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if not _has_audio(_run_ffprobe_json(video_path)):
        raise MCPVideoError(
            "duck_audio requires the video to have an audio track to duck against. "
            "Use add_audio to attach music to a silent video instead.",
            error_type="validation_error",
            code="missing_audio_stream",
        )

    filter_complex = (
        f"[1:a]volume={music_volume:g}[bg];"
        f"[bg][0:a]sidechaincompress=threshold={threshold:g}:ratio={ratio:g}"
        f":attack={attack:g}:release={release:g}[duck];"
        f"[0:a][duck]amix=inputs=2:duration=first:normalize=0[aout]"
    )

    with _timed_operation() as timing:
        _run_ffmpeg(
            [
                "-i",
                video_path,
                "-i",
                music_path,
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v?",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                DEFAULT_AUDIO_BITRATE,
                *_movflags_args(output),
                output,
            ]
        )

    return _build_edit_result(output, "duck_audio", timing)
