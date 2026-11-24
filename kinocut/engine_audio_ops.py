"""Audio attachment operations for the FFmpeg engine."""

from __future__ import annotations

import logging
import math
import os
import struct
from fractions import Fraction

from .defaults import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_DUCK_MUSIC_VOLUME,
    DEFAULT_DUCK_THRESHOLD,
    DEFAULT_DUCK_RATIO,
    DEFAULT_DUCK_ATTACK_MS,
    DEFAULT_DUCK_RELEASE_MS,
)
from .engine_probe import _build_audio_input_info, _build_video_info, _read_input_metadata
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
    _atomic_output,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value, _run_ffprobe_json
from .audio_guardrails import validate_audio_mix
from .errors import MCPVideoError
from .models import EditResult
from .validation import DURATION_POLICIES, AUDIO_DUCK_PARAMETER_RANGES
from .engine_audio_validation import _audio_number, _run_audio_ffmpeg
from .engine_audio_normalize_output import _validate_normalized_output
from .engine_media_timeline import _packet_extent, _primary_audio_timeline, _timestamp
from .limits import MAX_VIDEO_DURATION
from .validation_errors import exception_kind, rejected_value

logger = logging.getLogger(__name__)


def _build_audio_filters(
    volume: float, fade_in: float, fade_out: float, duration: float, *, audio_start: float = 0.0
) -> list[str]:
    """Fade the audible interval after native timestamps and requested delay."""
    filters: list[str] = []
    if volume != 1.0:
        filters.append(f"volume={_escape_ffmpeg_filter_value(str(volume))}")
    if fade_in > 0:
        start = _escape_ffmpeg_filter_value(str(audio_start) if audio_start else "0")
        filters.append(f"afade=t=in:st={start}:d={_escape_ffmpeg_filter_value(str(fade_in))}")
    if fade_out > 0:
        fade_start = audio_start + max(0.0, duration - fade_out)
        filters.append(
            f"afade=t=out:st={_escape_ffmpeg_filter_value(str(fade_start))}:"
            f"d={_escape_ffmpeg_filter_value(str(fade_out))}"
        )
    return filters


def _build_mix_audio_args(
    video_path: str,
    audio_path: str,
    filters: list[str],
    start_time: float | None,
    output: str,
    duration_policy: str,
    video_duration: float | None,
) -> list[str]:
    """Construct FFmpeg arguments for add_audio in mix mode.

    The added track is one chain: [1:a:0] -> optional adelay -> filters -> [a1].
    Mix mode disables amix's default 1/n normalization (``normalize=0``) so both
    tracks sum at unity instead of being attenuated ~6 dB (issue #289).
    """
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
    # Referencing [1:a:0] a second time mid-chain is invalid filtergraph syntax
    # even where some FFmpeg builds tolerate it.
    if start_time:
        safe_delay = _escape_ffmpeg_filter_value(str(int(start_time * 1000)))
        # all=1 delays every channel: a two-value list leaves channel 3+ of 5.1 undelayed.
        second_chain = f"[1:a:0]adelay={safe_delay}:all=1,{af}[a1]"
    else:
        second_chain = f"[1:a:0]{af}[a1]"
    filter_complex = (
        f"[0:a:0]aresample=async=1:first_pts=0[a0];{second_chain};"
        f"[a0][a1]amix=inputs=2:duration={amix_duration}:normalize=0[aout]"
    )
    loop_prefix = (
        ["-stream_loop", "-1", "-t", str(video_duration)]
        if duration_policy == "loop_audio" and video_duration is not None
        else []
    )
    return [
        "-i",
        video_path,
        *loop_prefix,
        "-i",
        audio_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
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


def _build_replace_audio_args(
    video_path: str,
    audio_path: str,
    filters: list[str],
    start_time: float | None,
    output: str,
    duration_policy: str,
    video_duration: float | None,
) -> list[str]:
    """Construct FFmpeg arguments for add_audio in replace (or add) mode.

    Non-shortest policies cap output at the video length. Mix-mode looping
    is handled separately with a duration-bounded audio input.
    """
    loop_prefix = ["-stream_loop", "-1"] if duration_policy == "loop_audio" else []
    audio_filters = list(filters)
    if duration_policy == "pad_audio":
        audio_filters.append("apad")
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
        delay_chain = f"[1:a:0]adelay={safe_delay}:all=1"
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
        return _build_mix_audio_args(
            video_path, audio_path, filters, start_time, output, duration_policy, video_duration
        )
    return _build_replace_audio_args(
        video_path, audio_path, filters, start_time, output, duration_policy, video_duration
    )


def _validate_duration_policy(duration_policy: str, mix: bool) -> None:
    """Validate the duration policy without echoing hostile input into errors."""

    if not isinstance(duration_policy, str) or duration_policy not in DURATION_POLICIES:
        # Never echo the raw (possibly hostile) value back into a public error.
        raise MCPVideoError(
            f"duration_policy must be one of {DURATION_POLICIES}",
            error_type="validation_error",
            code="invalid_duration_policy",
        )
    if mix and duration_policy == "pad_audio":
        # Mix-mode padding has no implemented duration-bounded input chain.
        # Keep its existing fail-closed policy; looping is now bounded above.
        raise MCPVideoError(
            f"duration_policy={rejected_value(duration_policy)!r} is not supported with mix=True; "
            "use keep_video, loop_audio, trim_audio, or shortest",
            error_type="validation_error",
            code="unsupported_duration_policy_for_mix",
        )


def _add_audio_guardrail_warnings(video_info, audio_path, audio_probe, volume, start_time) -> list[str]:
    """Guardrail messages for the result envelope: clipping, mix and timing risks.

    They travel in ``EditResult.warnings`` so the calling agent sees them;
    ``warnings.warn`` only reached the server's stderr, once per location.
    """

    # The attached audio is commonly an audio-only file (e.g. a voiceover WAV),
    # so probe it with an audio-aware probe — otherwise a valid WAV is misreported
    # as "No video stream found" (issue #7).
    try:
        audio_info = _build_audio_input_info(audio_path, audio_probe)
        return [
            f"[AUDIO GUARDRAIL] {message}"
            for message in validate_audio_mix(video_info, audio_info, volume=volume, start_time=start_time or 0.0)
        ]
    except Exception as exc:
        logger.warning("[AUDIO GUARDRAIL] Could not validate audio mix: %s", exception_kind(exc))
        return ["[AUDIO GUARDRAIL] Could not validate audio mix; listen before publishing."]


def _dropped_stream_warnings(probe: dict, *, uses_first_audio: bool, input_role: str = "source") -> list[str]:
    """Describe audio and subtitle drops implied by the explicit stream maps."""
    streams = probe.get("streams", [])
    audio = sum(1 for stream in streams if stream.get("codec_type") == "audio")
    subtitles = sum(1 for stream in streams if stream.get("codec_type") == "subtitle")
    messages: list[str] = []
    if audio and not uses_first_audio:
        messages.append(
            f"All {audio} source audio track(s) were dropped to replace existing audio. "
            "Use mix=True to include the first source track."
        )
    elif audio > 1:
        messages.append(
            f"{audio - 1} additional audio track(s) in the {input_role} are not carried into the output; "
            "only the first contributes to the output audio."
        )
    if subtitles > 0:
        messages.append(f"{subtitles} subtitle stream(s) in the {input_role} are not carried into the output.")
    return messages


def _validate_add_params(volume, fade_in, fade_out, mix, start_time):
    if not isinstance(mix, bool):
        raise MCPVideoError("mix must be a boolean", error_type="validation_error", code="invalid_parameter")
    volume = _audio_number(volume, "volume", 0, math.inf)
    fade_in = _audio_number(fade_in, "fade_in", 0, MAX_VIDEO_DURATION)
    fade_out = _audio_number(fade_out, "fade_out", 0, MAX_VIDEO_DURATION)
    if start_time is not None:
        start_time = _audio_number(start_time, "start_time", 0, MAX_VIDEO_DURATION)
    return volume, fade_in, fade_out, start_time


def _render_audio_edit(args: list[str], output: str, operation: str) -> EditResult:
    """Publish only after encoding, decoding and result construction succeed."""
    with _atomic_output(output) as staged, _timed_operation() as timing:
        _validate_output_path(staged)
        _run_audio_ffmpeg(["-xerror", *args[:-1], staged], runner=_run_ffmpeg)
        _validate_normalized_output(staged, "aac", audio_only=True)
        result = _build_edit_result(staged, operation, timing)
    return result.model_copy(update={"output_path": output, "elapsed_ms": timing["elapsed_ms"]})


def _parse_rate(value: object) -> Fraction | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    num, den = value.split("/", 1)
    if not (num.isdigit() and den.isdigit()):
        return None
    n, d = int(num), int(den)
    return Fraction(n, d) if n > 0 and d > 0 else None


def _iter_iso_boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", buf[pos : pos + 8])
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield kind, pos + hdr, pos + size
        pos += size


def _read_mp4_moov(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            file_size = fh.tell()
            pos = 0
            for _ in range(256):
                if pos + 8 > file_size:
                    return None
                fh.seek(pos)
                hdr = fh.read(8)
                if len(hdr) < 8:
                    return None
                size, kind = struct.unpack(">I4s", hdr)
                hdr_len = 8
                if size == 1:
                    ext = fh.read(8)
                    if len(ext) < 8:
                        return None
                    size = struct.unpack(">Q", ext)[0]
                    hdr_len = 16
                elif size == 0:
                    size = file_size - pos
                if size < hdr_len or pos + size > file_size:
                    return None
                if kind == b"moov":
                    return None if size - hdr_len > 16 * 1024 * 1024 else fh.read(size - hdr_len)
                pos += size
    except OSError:
        return None
    return None


def _elst_exceeds_bframe_reorder(elst: bytes, max_allowed_media_time: int) -> bool:
    if len(elst) < 8:
        return True
    ver = elst[0]
    count = struct.unpack(">I", elst[4:8])[0]
    if count != 1:
        return True
    if ver == 1:
        if len(elst) < 24:
            return True
        _, media_time = struct.unpack(">Qq", elst[8:24])
    elif ver == 0:
        if len(elst) < 16:
            return True
        _, media_time = struct.unpack(">Ii", elst[8:16])
    else:
        return True
    return media_time < 0 or media_time > max_allowed_media_time


def _mp4_has_nontrivial_video_edit_list(path: str, stream: dict, fps: Fraction) -> bool:
    """Fail closed to packet scan if MP4/MOV video tracks carry trimming edit lists."""
    tb = _parse_rate(stream.get("time_base"))
    if tb is None:
        return True
    try:
        max_b = max(int(stream.get("has_b_frames") or 0), 0)
    except (TypeError, ValueError):
        return True
    frame_ticks = round(float(1 / (fps * tb)))
    max_allowed = max_b * max(frame_ticks, 0)
    moov = _read_mp4_moov(path)
    if moov is None:
        return True
    for kind, s, e in _iter_iso_boxes(moov, 0, len(moov)):
        if kind != b"trak":
            continue
        is_video = False
        elsts: list[bytes] = []
        for tk, ts, te in _iter_iso_boxes(moov, s, e):
            if tk == b"mdia":
                for mk, ms, me in _iter_iso_boxes(moov, ts, te):
                    if mk == b"hdlr" and me - ms >= 12 and moov[ms + 8 : ms + 12] == b"vide":
                        is_video = True
            elif tk == b"edts":
                for ek, es, ee in _iter_iso_boxes(moov, ts, te):
                    if ek == b"elst":
                        elsts.append(moov[es:ee])
        if is_video and any(_elst_exceeds_bframe_reorder(elst, max_allowed) for elst in elsts):
            return True
    return False


def _picture_extent(path: str, metadata: dict) -> tuple[float, float]:
    """Trust matching CFR headers; measure packets for VFR, edit lists, or ambiguous timelines."""
    container = metadata.get("format", {})
    stream = next(stream for stream in metadata["streams"] if stream.get("codec_type") == "video")
    duration, total = _timestamp(stream.get("duration")), _timestamp(container.get("duration"))
    start, origin = _timestamp(stream.get("start_time")), _timestamp(container.get("start_time"))
    fps = _parse_rate(stream.get("avg_frame_rate"))
    nb_frames_raw = stream.get("nb_frames")
    try:
        nb_frames = int(nb_frames_raw) if nb_frames_raw is not None else 0
    except (TypeError, ValueError):
        nb_frames = 0
    fmt_names = {part.strip().lower() for part in str(container.get("format_name") or "").split(",")}
    is_isobmff = bool(fmt_names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
    if (
        duration is not None
        and duration > 0
        and total is not None
        and abs(duration - total) <= 0.001
        and start is not None
        and origin is not None
        and abs(start - origin) <= 0.001
        and fps is not None
        and stream.get("avg_frame_rate") == stream.get("r_frame_rate")
        and nb_frames > 0
        and abs((nb_frames / float(fps)) - duration) <= 0.001
        and (not is_isobmff or not _mp4_has_nontrivial_video_edit_list(path, stream, fps))
    ):
        return start, duration
    return _packet_extent(path, "v:0")


def _attachment_window(video_path, audio_path, video_probe, audio_probe, start_time, duration_policy, mix):
    picture_start, picture_duration = _picture_extent(video_path, video_probe)
    picture_origin = _timestamp(video_probe.get("format", {}).get("start_time")) or 0.0
    picture_end = picture_start - picture_origin + picture_duration
    audio_start, audio_duration = _primary_audio_timeline(audio_path, audio_probe)
    audio_origin = _timestamp(audio_probe.get("format", {}).get("start_time")) or 0.0
    # Match adelay's existing millisecond quantization rather than moving media.
    audible_start = max(0.0, audio_start - audio_origin) + int((start_time or 0) * 1000) / 1000
    audible_end = picture_end if duration_policy == "loop_audio" else min(picture_end, audible_start + audio_duration)
    if duration_policy == "shortest" and mix and _has_audio(video_probe):
        source_start, source_duration = _primary_audio_timeline(video_path, video_probe)
        audible_end = min(audible_end, source_start - picture_origin + source_duration)
    return audible_start, max(0.0, audible_end - audible_start), picture_end


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
    volume, fade_in, fade_out, start_time = _validate_add_params(volume, fade_in, fade_out, mix, start_time)
    _validate_duration_policy(duration_policy, mix)
    video_path = _validate_input_path(video_path)
    audio_path = _validate_input_path(audio_path)
    output = output_path or _auto_output(video_path, "audio")
    _validate_output_path(output)

    video_probe = _read_input_metadata(video_path, require_video=True)
    video_info = _build_video_info(video_path, video_probe)
    audio_probe = video_probe if audio_path == video_path else _read_input_metadata(audio_path)
    source_has_audio = _has_audio(video_probe)
    audible_start, audible_duration, picture_end = _attachment_window(
        video_path, audio_path, video_probe, audio_probe, start_time, duration_policy, mix
    )
    guardrails = _add_audio_guardrail_warnings(video_info, audio_path, audio_probe, volume, start_time)

    filters = [
        "aresample=async=1:first_pts=0",
        *_build_audio_filters(
            volume,
            min(fade_in, audible_duration),
            min(fade_out, audible_duration),
            audible_duration,
            audio_start=audible_start,
        ),
    ]
    cmd = _build_add_audio_args(
        video_path,
        audio_path,
        filters,
        mix,
        start_time,
        source_has_audio,
        output,
        duration_policy=duration_policy,
        video_duration=picture_end,
    )
    result = _render_audio_edit(cmd, output, "add_audio")

    warnings = _dropped_stream_warnings(video_probe, uses_first_audio=mix or audio_path == video_path)
    if audio_path != video_path:
        warnings.extend(_dropped_stream_warnings(audio_probe, uses_first_audio=True, input_role="attached media"))
    if mix and source_has_audio:
        warnings.append("Both tracks are summed without loudness normalization and may clip; listen before publishing.")
    if duration_policy == "shortest":
        warnings.append(
            "duration_policy='shortest' may shorten the output below the source "
            "video duration (the outro can be trimmed). Use 'keep_video' to preserve it."
        )

    return result.model_copy(update={"warnings": [*result.warnings, *warnings, *guardrails]})


def _validate_duck_params(
    music_volume: float,
    threshold: float,
    ratio: float,
    attack: float,
    release: float,
) -> tuple[float, ...]:
    """Validate types before numeric comparison and match the backend domain."""
    values = (music_volume, threshold, ratio, attack, release)
    names = ("music_volume", "threshold", "ratio", "attack", "release")
    clean = tuple(
        _audio_number(value, name, *AUDIO_DUCK_PARAMETER_RANGES[name])
        for name, value in zip(names, values, strict=True)
    )
    if clean[0] <= 0:
        raise MCPVideoError("music_volume must be positive", error_type="validation_error", code="invalid_parameter")
    return clean


def _duck_filter(music_volume: float, threshold: float, ratio: float, attack: float, release: float) -> str:
    volume, threshold_s, ratio_s, attack_s, release_s = (
        _escape_ffmpeg_filter_value(str(value)) for value in (music_volume, threshold, ratio, attack, release)
    )
    return (
        f"[1:a:0]volume={volume}[bg];"
        f"[bg][0:a:0]sidechaincompress=threshold={threshold_s}:ratio={ratio_s}"
        f":attack={attack_s}:release={release_s}[duck];"
        "[0:a:0][duck]amix=inputs=2:duration=first:normalize=0[aout]"
    )


def duck_audio(
    video_path: str,
    music_path: str,
    output_path: str | None = None,
    music_volume: float = DEFAULT_DUCK_MUSIC_VOLUME,
    threshold: float = DEFAULT_DUCK_THRESHOLD,
    ratio: float = DEFAULT_DUCK_RATIO,
    attack: float = DEFAULT_DUCK_ATTACK_MS,
    release: float = DEFAULT_DUCK_RELEASE_MS,
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

    music_volume, threshold, ratio, attack, release = _validate_duck_params(
        music_volume, threshold, ratio, attack, release
    )

    source_probe = _run_ffprobe_json(video_path)
    if not _has_audio(source_probe):
        raise MCPVideoError(
            "duck_audio requires the video to have an audio track to duck against. "
            "Use add_audio to attach music to a silent video instead.",
            error_type="validation_error",
            code="missing_audio_stream",
        )

    _primary_audio_timeline(video_path, source_probe)
    music_probe = source_probe if music_path == video_path else _run_ffprobe_json(music_path)
    _primary_audio_timeline(music_path, music_probe)

    args = [
        "-i",
        video_path,
        "-i",
        music_path,
        "-filter_complex",
        _duck_filter(music_volume, threshold, ratio, attack, release),
        "-map",
        "0:v:0?",
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
    result = _render_audio_edit(args, output, "duck_audio")
    warnings = _dropped_stream_warnings(source_probe, uses_first_audio=True)
    if music_path != video_path:
        warnings.extend(_dropped_stream_warnings(music_probe, uses_first_audio=True, input_role="music input"))
    return result.model_copy(update={"warnings": [*result.warnings, *warnings]})
