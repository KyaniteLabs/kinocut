"""Pure plan construction using a closed set of real KinoCut tool contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePath

from .parser import Direction

ALLOWED_TOOLS = frozenset(
    {
        "video_trim",
        "video_ai_remove_silence",
        "video_speed",
        "video_crop",
        "video_resize",
        "video_normalize_audio",
        "video_ai_transcribe",
        "video_subtitles",
        "video_thumbnail",
        "video_add_audio",
    }
)
FORMATS = {"vertical": (1080, 1920), "square": (1080, 1080), "landscape": (1920, 1080)}


@dataclass
class Plan:
    input_path: str
    output_path: str
    steps: list[dict]
    assumptions: list[str]
    question: str | None
    unrecognized: list[str]
    estimate: dict
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def _plan_timing(d, duration, has_audio, add, assumptions, question):
    """Trim, silence, speed and target length, in edit order. Returns (duration, question)."""
    if d.trim_start or d.trim_end:
        if duration is not None and duration - d.trim_start - d.trim_end < 0.01:
            question = question or "The requested cuts remove the whole clip; how much should I keep?"
            assumptions.append("The trim was skipped because it would leave no video or less than 0.01 seconds.")
        elif d.trim_end and duration is None:
            question = question or "How long is the source clip so I can trim its end?"
            assumptions.append("End trimming needs source duration; this trim is deferred.")
        else:
            args = {"start": d.trim_start, "accurate": True}
            if duration is not None:
                duration -= d.trim_start + d.trim_end
                args["duration"] = duration
            add("video_trim", "Skip the requested opening and ending seconds.", **args)
            assumptions.append("Trims use seconds from the original clip and frame-accurate seeking.")
    if d.remove_silence and has_audio:
        add(
            "video_ai_remove_silence",
            "Cut dead air while keeping a small margin around sound.",
            silence_threshold=-50.0,
            min_silence_duration=0.5,
            keep_margin=0.1,
        )
        assumptions.append(
            "Silence means below -50 dB for at least 0.5 seconds, with 0.1 seconds of margin; remaining duration is an upper bound."
        )
    if d.speed:
        add("video_speed", "Adjust the pace before creating synchronized captions.", factor=d.speed)
        assumptions.append(f"Requested pacing uses {d.speed:g}x playback speed.")
        if duration is not None:
            duration /= d.speed
    if d.target_length:
        if duration is None or duration > d.target_length:
            add(
                "video_trim",
                "Limit the final cut to the requested length.",
                start=0.0,
                duration=d.target_length,
                accurate=True,
            )
            assumptions.append(
                f"Keep up to {d.target_length:g} seconds from the beginning after cleanup; this does not select the best part. If cleanup leaves less, keep the shorter cut."
            )
            if duration is not None:
                duration = min(duration, d.target_length)
        else:
            assumptions.append(
                "The clip is already shorter than or equal to the target; no padding or extra trim is planned."
            )
    return duration, question


def _plan_format(d, info, add, assumptions):
    fmt = d.platform or "vertical"
    if not d.platform:
        assumptions.append("Reframing defaults to vertical when no format is requested.")
    width, height = FORMATS[fmt]
    if d.reframe:
        sw, sh = info.get("display_width", info.get("width")), info.get("display_height", info.get("height"))
        if sw and sh:
            cw = max(2, int(min(sw, sh * width / height)) // 2 * 2)
            ch = max(2, int(min(sh, sw * height / width)) // 2 * 2)
            add("video_crop", "Center the frame before resizing.", width=cw, height=ch)
        assumptions.append(
            "Use a center crop: there is no executable face-tracking tool in this plan; check that the face stays in frame."
        )
        if not sw or not sh:
            assumptions.append(
                "Source dimensions are unknown, so center cropping is deferred until a probed plan is made."
            )
    add("video_resize", "Fit the requested delivery format.", width=width, height=height, quality="high")
    assumptions.append(
        f"Use {fmt} {width}x{height}, standard high quality encoding, and black padding where needed to avoid stretching."
    )


def _bind_paths(d, steps):
    """Bind deterministic artifacts next to the requested output, with no filesystem access."""
    out = PurePath(d.output_path)
    current = d.input_path
    srt = str(out.with_name(f"{out.stem}.direct.srt"))
    video_indices = [i for i, s in enumerate(steps) if s["tool"] not in {"video_ai_transcribe", "video_thumbnail"}]
    for i, step in enumerate(steps):
        args = step["args"]
        if step["tool"] == "video_add_audio":
            args.update(video_path=current, audio_path=current)
        else:
            args["input_path"] = current
        if step["tool"] == "video_ai_transcribe":
            args["output_srt"] = srt
        elif step["tool"] == "video_thumbnail":
            args["output_path"] = str(out.with_name(f"{out.stem}.thumbnail.jpg"))
        else:
            if step["tool"] == "video_subtitles":
                args["subtitle_path"] = srt
            args["output_path"] = (
                str(out) if i == video_indices[-1] else str(out.with_name(f"{out.stem}.direct-{i + 1:02d}{out.suffix}"))
            )
            current = args["output_path"]
    return out, video_indices


def plan_direction(direction: Direction, probe: dict | None) -> Plan:
    """Plan in edit order. Duration after silence removal is an upper bound."""
    d = direction
    info = probe or {}
    assumptions = list(d.assumptions)
    question = d.question
    steps = []
    duration = info.get("duration")
    has_audio = info.get("has_audio", info.get("audio_codec") is not None if "audio_codec" in info else True)

    def add(tool, why, **args):
        steps.append({"tool": tool, "args": args, "why": why})

    duration, question = _plan_timing(d, duration, has_audio, add, assumptions, question)
    if d.platform or d.reframe:
        _plan_format(d, info, add, assumptions)
    if d.loudness and has_audio and not d.mute:
        add("video_normalize_audio", "Bring the sound to a consistent listening level.", target_lufs=-14.0)
        assumptions.append("Normalize sound to -14 LUFS using the existing loudness defaults.")
    if d.captions and has_audio:
        add("video_ai_transcribe", "Transcribe the final timing for synchronized captions.", model="base")
        assumptions.append(
            "Captions use the existing local base transcription model, automatic language, and default subtitle style; no speech means captions are skipped."
        )
    if d.mute and has_audio:
        add(
            "video_add_audio",
            "Silence all audio while preserving the picture and timing.",
            volume=0.0,
            mix=False,
            duration_policy="keep_video",
        )
        assumptions.append(
            "Mute means silence all audio using zero gain, preserve the full video, and transcribe captions before muting; other audio insertion defaults stay unchanged."
        )
        if d.loudness:
            assumptions.append("Muting takes priority over making the audio louder.")
    if d.captions and has_audio:
        add("video_subtitles", "Burn captions into the finished cut.")
    if not has_audio and (d.captions or d.loudness or d.remove_silence):
        assumptions.append("The source has no audio stream; silence removal, loudness and captions are skipped.")
    if d.thumbnail:
        add("video_thumbnail", "Take a thumbnail from the final video.", timestamp=0.0)
        assumptions.append("The thumbnail uses the first frame of the final video.")

    out, video_indices = _bind_paths(d, steps)
    if not steps and not d.explicit_negation:
        question = question or "What should change: length, captions, sound, or format?"
    if d.unrecognized:
        assumptions.append("Unrecognized words are listed for review and do not create edit steps.")
    estimate = {"step_count": len(steps)}
    if probe is not None:
        estimate.update(duration_seconds=duration, duration_is_upper_bound=bool(d.remove_silence and has_audio))
    return Plan(
        d.input_path,
        str(out) if video_indices else d.input_path,
        steps,
        assumptions,
        question,
        list(d.unrecognized),
        estimate,
    )
