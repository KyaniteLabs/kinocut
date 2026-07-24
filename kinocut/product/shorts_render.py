"""Review-gated render orchestration for shorts plans.

Fails closed without a current approve decision. Uses existing trim/resize/
audio/caption/thumbnail engines only. No network or posting.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..engine_audio_normalize import normalize_audio
from ..engine_edit import trim
from ..engine_resize import resize
from ..engine_thumbnail import thumbnail
from ..ffmpeg_helpers import _build_ffmpeg_cmd, _run_ffmpeg, _validate_input_path
from .captions import CaptionConfig, WordTiming, build_caption_artifact
from .clip_pipeline import clip_moment
from .config import normalise_platform
from .models import CandidateMoment, canonical_dedup_key
from .shorts_plan import RenderRecord, ShortsPlan, load_shorts_plan, save_shorts_plan
from .shorts_review import resolve_approved_candidate

__all__ = ["render_approved_candidate"]


def _candidate_digest(candidate: CandidateMoment) -> str:
    payload = json.dumps(candidate.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _render_digest(
    *,
    source_sha256: str,
    candidate_digest: str,
    platform: str,
    start: float,
    end: float,
    config: dict[str, Any],
) -> str:
    material = (
        f"render-v5:{source_sha256}:{candidate_digest}:{platform}:"
        f"{start}:{end}:{json.dumps(config, sort_keys=True, separators=(',', ':'), default=str)}"
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _words_for(plan: ShortsPlan, candidate: CandidateMoment) -> list[WordTiming]:
    """Prefer real word timings; fall back to even segment splits."""
    segment_ids = {
        seg.segment_id for seg in plan.transcript if seg.end > candidate.start and seg.start < candidate.end
    }
    words: list[WordTiming] = []
    if plan.transcript_words:
        for item in plan.transcript_words:
            if item.segment_id not in segment_ids or item.end <= candidate.start or item.start >= candidate.end:
                continue
            start = max(item.start, candidate.start) - candidate.start
            end = min(item.end, candidate.end) - candidate.start
            if end <= start:
                end = start + 0.001
            words.append(WordTiming(word=item.word, start=start, end=end, probability=item.probability))
        if words:
            return words
    for segment in plan.transcript:
        if segment.segment_id not in segment_ids:
            continue
        tokens = segment.text.split()
        if not tokens:
            continue
        step = (segment.end - segment.start) / len(tokens)
        for index, token in enumerate(tokens):
            global_start = segment.start + index * step
            global_end = segment.start + (index + 1) * step
            if global_end <= candidate.start or global_start >= candidate.end:
                continue
            start = max(global_start, candidate.start) - candidate.start
            end = min(global_end, candidate.end) - candidate.start
            words.append(
                WordTiming(word=token, start=start, end=max(end, start + 0.001), probability=segment.confidence)
            )
    return words


def _clip_bounds(candidate: CandidateMoment, platform: str):
    internal = normalise_platform(platform)
    clipped = clip_moment(candidate, platform=internal)
    rendered = candidate.model_copy(
        update={
            "start": clipped.start_seconds,
            "end": clipped.end_seconds,
            "dedup_key": canonical_dedup_key(
                start=clipped.start_seconds,
                end=clipped.end_seconds,
                excerpt=candidate.transcript_excerpt,
                sensitivity=candidate.sensitivity,
            ),
        }
    )
    warning = None
    if clipped.was_clipped or clipped.review_warning is not None:
        warning = clipped.review_warning or (
            f"moment {candidate.candidate_id!r} clipped for {internal}"
        )
    return clipped, rendered, warning


def _payload_for(record: RenderRecord, clipped, *, cache_hit: bool) -> dict[str, Any]:
    payload = record.model_copy(update={"cache_hit": cache_hit}).model_dump(mode="json")
    payload.update(
        {
            "effective_start_seconds": clipped.start_seconds,
            "effective_end_seconds": clipped.end_seconds,
            "original_start_seconds": clipped.original_start_seconds,
            "original_end_seconds": clipped.original_end_seconds,
            "was_clipped": clipped.was_clipped,
            "review_warning": clipped.review_warning,
        }
    )
    return payload


def _render_media(
    *,
    source_path: str,
    platform_dir: str,
    final_path: str,
    start: float,
    end: float,
    audio_cfg: dict[str, Any],
) -> str:
    duration = end - start
    fade = float(audio_cfg.get("fade_seconds", 0.05))
    trimmed = trim(
        source_path,
        start=start,
        duration=duration,
        output_path=os.path.join(platform_dir, "trimmed.mp4"),
    )
    vertical = resize(
        trimmed.output_path,
        aspect_ratio="9:16",
        output_path=os.path.join(platform_dir, "vertical-raw.mp4"),
    )
    faded = os.path.join(platform_dir, "vertical-faded.mp4")
    fade_out = max(0.0, duration - fade)
    _run_ffmpeg(
        _build_ffmpeg_cmd(
            vertical.output_path,
            output_path=faded,
            video_codec="copy",
            audio_filter=(
                f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={fade_out:.3f}:d={fade:.3f}"
            ),
        )
    )
    return normalize_audio(
        faded,
        target_lufs=float(audio_cfg.get("lufs", -14.0)),
        output_path=final_path,
    ).output_path


def _render_one_platform(
    plan: ShortsPlan,
    candidate: CandidateMoment,
    *,
    platform: str,
    base_dir: str,
    source_path: str,
    cand_digest: str,
    audio_cfg: dict[str, Any],
    records: list[RenderRecord],
) -> tuple[dict[str, Any], RenderRecord | None, str | None]:
    platform_dir = os.path.join(base_dir, platform)
    os.makedirs(platform_dir, exist_ok=True)
    final_path = os.path.join(platform_dir, "vertical.mp4")
    clipped, rendered, warning = _clip_bounds(candidate, platform)
    digest = _render_digest(
        source_sha256=plan.intake.source_sha256,
        candidate_digest=cand_digest,
        platform=platform,
        start=clipped.start_seconds,
        end=clipped.end_seconds,
        config=plan.config if isinstance(plan.config, dict) else {},
    )
    previous = next(
        (
            record
            for record in records
            if record.candidate_id == candidate.candidate_id
            and record.platform == platform
            and record.render_digest == digest
            and os.path.isfile(record.output_path)
        ),
        None,
    )
    if previous is not None:
        return _payload_for(previous, clipped, cache_hit=True), None, warning

    finished = _render_media(
        source_path=source_path,
        platform_dir=platform_dir,
        final_path=final_path,
        start=clipped.start_seconds,
        end=clipped.end_seconds,
        audio_cfg=audio_cfg,
    )
    srt_path = os.path.join(platform_dir, "captions.srt")
    body = build_caption_artifact(_words_for(plan, rendered), config=CaptionConfig()).srt_body
    Path(srt_path).write_text(body + ("" if body.endswith("\n") else "\n"), encoding="utf-8")
    thumb = thumbnail(finished, output_path=os.path.join(platform_dir, "thumbnail.jpg")).output_path
    record = RenderRecord(
        candidate_id=candidate.candidate_id,
        platform=platform,  # type: ignore[arg-type]
        output_path=finished,
        render_digest=digest,
        editable_subtitles=srt_path,
        thumbnail_path=thumb,
        cache_hit=False,
    )
    return _payload_for(record, clipped, cache_hit=False), record, warning


def render_approved_candidate(
    plan_path_or_dir: str,
    *,
    candidate_id: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Render platform drafts for an approved candidate and persist the plan."""
    plan = load_shorts_plan(plan_path_or_dir)
    candidate = resolve_approved_candidate(plan, candidate_id)
    source_path = _validate_input_path(plan.intake.source_path)
    base_dir = os.path.realpath(output_path or os.path.join(plan.output_dir, candidate.candidate_id))
    if os.path.splitext(base_dir)[1]:
        base_dir = os.path.dirname(base_dir)
    os.makedirs(base_dir, exist_ok=True)

    records: list[RenderRecord] = list(plan.renders)
    emitted: list[dict[str, Any]] = []
    warnings: list[str] = []
    cand_digest = _candidate_digest(candidate)
    render_cfg = plan.config.get("render", {}) if isinstance(plan.config, dict) else {}
    audio_cfg = render_cfg.get("audio", {}) if isinstance(render_cfg, dict) else {}
    if not isinstance(audio_cfg, dict):
        audio_cfg = {}

    for platform in plan.platforms:
        payload, new_record, warning = _render_one_platform(
            plan,
            candidate,
            platform=platform,
            base_dir=base_dir,
            source_path=source_path,
            cand_digest=cand_digest,
            audio_cfg=audio_cfg,
            records=records,
        )
        if warning is not None:
            warnings.append(warning)
        if new_record is not None:
            records = [
                item
                for item in records
                if not (item.candidate_id == candidate.candidate_id and item.platform == platform)
            ] + [new_record]
        emitted.append(payload)

    revised = plan.model_copy(update={"renders": tuple(records), "status": "rendered"})
    save_shorts_plan(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "rendered",
        "renders": emitted,
        "external_posting": False,
        "review_warnings": tuple(dict.fromkeys(warnings)),
    }
