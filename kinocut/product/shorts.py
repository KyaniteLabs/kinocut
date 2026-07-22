"""Shared human-gated orchestration for long-form stream repurposing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..engine_audio_normalize import normalize_audio
from ..engine_edit import trim
from ..engine_probe import probe
from ..engine_resize import resize
from ..engine_thumbnail import thumbnail
from ..engine_subtitles import subtitles
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _build_ffmpeg_cmd, _run_ffmpeg
from ..limits import MAX_AI_TRANSCRIBE_DURATION
from .captions import CaptionConfig, WordTiming, build_caption_artifact
from .config import ShortsConfig, config_from_mapping, externalise_platform
from .highlight_discovery import discover_highlights
from .models import CandidateMoment, HighlightDiscoveryConfig, TranscriptSegment
from .package import PackageConfig, PackageLineage, ThumbnailSpec, package_approved_clip


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class IntakeReport(_StrictModel):
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio_available: bool
    format: str | None = None
    problems: tuple[str, ...] = ()


class ReviewDecision(_StrictModel):
    candidate_id: str
    action: Literal["preview", "approve", "reject", "trim", "title_hook_edit", "sensitive_unsuitable"]
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    title: str | None = None
    hook: str | None = None
    sensitive: bool | None = None
    unsuitable: bool | None = None
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _validate_trim(self) -> ReviewDecision:
        if self.action == "trim" and (self.start is None or self.end is None or self.end <= self.start):
            raise ValueError("trim decisions require start < end")
        return self


class RenderRecord(_StrictModel):
    candidate_id: str
    platform: str
    output_path: str
    render_digest: str = Field(pattern=r"^[0-9a-f]{16}$")
    editable_subtitles: str
    thumbnail_path: str
    cache_hit: bool = False


class ShortsPlan(_StrictModel):
    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=r"^shorts_[0-9a-f]{16}$")
    status: Literal["review_required", "reviewed", "rendered", "packaged"] = "review_required"
    project_dir: str
    output_dir: str
    intake: IntakeReport
    platforms: tuple[str, ...]
    config: dict[str, Any]
    transcript: tuple[TranscriptSegment, ...]
    proposals: tuple[CandidateMoment, ...]
    decisions: tuple[ReviewDecision, ...] = ()
    renders: tuple[RenderRecord, ...] = ()
    package_manifests: tuple[str, ...] = ()
    external_posting: bool = False


_PLAN_CACHE: dict[str, ShortsPlan] = {}


def _error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {cause} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_path(plan: ShortsPlan) -> str:
    return os.path.join(plan.output_dir, f"{plan.job_id}.plan.json")


def _save(plan: ShortsPlan) -> ShortsPlan:
    os.makedirs(plan.output_dir, exist_ok=True)
    path = _plan_path(plan)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(plan.model_dump(mode="json"), handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(tmp, path)
    _PLAN_CACHE[plan.job_id] = plan
    return plan


def _load(job_or_dir: str, *, candidate_id: str | None = None) -> ShortsPlan:
    if job_or_dir in _PLAN_CACHE:
        return _PLAN_CACHE[job_or_dir]
    path = Path(job_or_dir)
    candidates: list[Path]
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        candidates = sorted(path.glob("shorts_*.plan.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        candidates += (
            sorted((path / "shorts").glob("shorts_*.plan.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            if (path / "shorts").is_dir()
            else []
        )
    else:
        candidates = []
    for item in candidates:
        plan = ShortsPlan.model_validate_json(item.read_text(encoding="utf-8"))
        _PLAN_CACHE[plan.job_id] = plan
        if candidate_id is None or any(p.candidate_id == candidate_id for p in plan.proposals):
            return plan
    raise _error(
        "The saved shorts plan could not be found.",
        code="shorts_plan_not_found",
        cause="The job id or project directory does not contain a plan receipt.",
        recovery="Run `kino shorts <input>` to create proposals, then retry with its job id.",
    )


def _segments(payload: Any) -> tuple[TranscriptSegment, ...]:
    if payload is None:
        return ()
    result: list[TranscriptSegment] = []
    for index, item in enumerate(payload):
        if isinstance(item, TranscriptSegment):
            result.append(item)
            continue
        raw = dict(item)
        data = {
            "segment_id": raw.get("segment_id", f"seg_{index:06d}"),
            "start": raw.get("start"),
            "end": raw.get("end"),
            "text": str(raw.get("text", "")).strip(),
            "speaker": raw.get("speaker"),
            "confidence": raw.get("confidence", max(0.0, min(1.0, 1.0 + float(raw.get("avg_logprob", 0.0))))),
            "is_silence": raw.get("is_silence", False),
        }
        if not data["text"]:
            continue
        result.append(TranscriptSegment.model_validate(data))
    return tuple(result)


def _transcribe(
    source_path: str, *, duration: float, model: str = "base", language: str | None = None
) -> tuple[TranscriptSegment, ...]:
    from ..ai_engine.transcribe import ai_transcribe
    from ..ai_engine.transcribe_longform import transcribe_longform

    try:
        if duration > MAX_AI_TRANSCRIBE_DURATION:
            longform = transcribe_longform(source_path, model=model, language=language)
            return _segments(segment.model_dump(mode="json") for segment in longform.segments)
        result = ai_transcribe(source_path, model=model, language=language)
    except MCPVideoError:
        raise
    except Exception as exc:
        raise _error(
            "The recording could not be transcribed.",
            code="shorts_transcription_failed",
            cause=str(exc),
            recovery="Install the local transcription extra or configure an opt-in provider, then resume the saved intake.",
        ) from exc
    return _segments(result.get("segments", ()))


def _config_from_flat(config: dict[str, Any]) -> ShortsConfig:
    nested = dict(config.pop("shorts_config", {}) or {})
    platforms = config.pop("platforms", None)
    if platforms is not None:
        nested["platforms"] = tuple(platforms)
    for key in ("min_clip_seconds", "max_clip_seconds", "output_dir", "resume_job_id"):
        if key in config and config[key] is not None:
            nested[key] = config.pop(key)
    render = dict(nested.get("render", {}) or {})
    for key in ("subject_reframe", "burned_captions", "captions_editable"):
        if key in config and config[key] is not None:
            render[key] = config.pop(key)
    if render:
        nested["render"] = render
    return config_from_mapping(nested)


def _dedupe_candidates(candidates: tuple[CandidateMoment, ...]) -> tuple[CandidateMoment, ...]:
    """Drop candidates whose time window substantially duplicates a stronger one."""
    kept: list[CandidateMoment] = []
    for candidate in candidates:
        duplicate = False
        for existing in kept:
            overlap = max(0.0, min(candidate.end, existing.end) - max(candidate.start, existing.start))
            shorter = min(candidate.end - candidate.start, existing.end - existing.start)
            if shorter > 0 and overlap / shorter >= 0.65:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return tuple(kept)


def shorts_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Inspect, transcribe, and propose moments; never render implicitly."""
    project_dir = kwargs.pop("project_dir", None)
    source_path = kwargs.pop("source_path", None)
    if args:
        source_path = args[0]
    if not isinstance(source_path, str) or not source_path:
        raise _error(
            "No recording was supplied.",
            code="shorts_source_required",
            cause="The source path is empty.",
            recovery="Pass a completed livestream recording path.",
        )

    raw_config = dict(kwargs.pop("config", {}) or {})
    raw_config.update(kwargs)
    transcript_payload = raw_config.pop("transcript_segments", None)
    model = str(raw_config.pop("model", "base"))
    language = raw_config.pop("language", None)
    cfg = _config_from_flat(raw_config)
    output_dir = os.path.realpath(cfg.output_dir or os.path.join(str(project_dir or os.getcwd()), "shorts"))

    if cfg.resume_job_id:
        plan = _load(cfg.resume_job_id)
        if _sha256(source_path) != plan.intake.source_sha256:
            raise _error(
                "The source changed since the saved job.",
                code="shorts_source_changed",
                cause="Its checksum no longer matches the intake receipt.",
                recovery="Restore the original recording or start a new shorts job.",
            )
        return plan.model_dump(mode="json")

    try:
        info = probe(source_path)
    except Exception as exc:
        if isinstance(exc, MCPVideoError):
            raise
        raise _error(
            "The recording could not be inspected.",
            code="shorts_intake_failed",
            cause=str(exc),
            recovery="Verify the file exists and can be opened by FFmpeg, then retry.",
        ) from exc
    if not info.audio_codec:
        raise _error(
            "The recording has no usable audio.",
            code="shorts_audio_missing",
            cause="No audio stream was detected.",
            recovery="Use a recording with an audio track or repair the source container.",
        )
    if not (cfg.intake.min_duration_seconds <= info.duration <= cfg.intake.max_duration_seconds):
        raise _error(
            "The recording duration is outside the configured intake range.",
            code="shorts_duration_unsupported",
            cause=f"Detected {info.duration:.1f}s; configured range is {cfg.intake.min_duration_seconds:.1f}-{cfg.intake.max_duration_seconds:.1f}s.",
            recovery="Choose a compatible recording or adjust the intake duration limits.",
        )

    transcript = _segments(transcript_payload) or _transcribe(
        source_path, duration=info.duration, model=model, language=language
    )
    if not transcript:
        raise _error(
            "Transcription produced no spoken segments.",
            code="shorts_empty_transcript",
            cause="The recording may be silent or the selected language/model could not recognize it.",
            recovery="Check the audio and transcription settings, then retry.",
        )
    discovery = discover_highlights(
        transcript,
        config=HighlightDiscoveryConfig(min_duration=cfg.min_clip_seconds, max_duration=cfg.max_clip_seconds),
    )
    proposals = _dedupe_candidates(discovery.candidates)
    if not proposals:
        raise _error(
            "No complete clip candidates were found.",
            code="shorts_no_candidates",
            cause="The transcript lacks a complete thought within the target duration.",
            recovery="Adjust clip duration settings or supply a clearer transcript.",
        )

    intake = IntakeReport(
        source_path=os.path.realpath(source_path),
        source_sha256=_sha256(source_path),
        duration=info.duration,
        width=info.width,
        height=info.height,
        audio_available=True,
        format=info.format,
        problems=(
            () if info.width >= 720 else ("source resolution is below 720p; safe padded composition will be used",)
        ),
    )
    config_json = cfg.model_dump(mode="json")
    seed = json.dumps({"source": intake.source_sha256, "config": config_json}, sort_keys=True, separators=(",", ":"))
    job_id = f"shorts_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
    plan = ShortsPlan(
        job_id=job_id,
        project_dir=os.path.realpath(str(project_dir or output_dir)),
        output_dir=output_dir,
        intake=intake,
        platforms=tuple(externalise_platform(p) for p in cfg.platforms),
        config=config_json,
        transcript=transcript,
        proposals=proposals,
    )
    return _save(plan).model_dump(mode="json")


def shorts_propose(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply non-rendering candidate edits and return the revised plan."""
    plan_payload = kwargs.pop("plan", None)
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    edits = kwargs.pop("edits", None) or kwargs.pop("edit", None) or {}
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = (
        ShortsPlan.model_validate(plan_payload)
        if plan_payload is not None
        else _load(str(job_id or project_dir), candidate_id=candidate_id)
    )
    if not candidate_id or not any(p.candidate_id == candidate_id for p in plan.proposals):
        raise _error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause="Its id is not in the saved proposal set.",
            recovery="Use a candidate id from `shorts_propose` output.",
        )
    action = str(edits.pop("action", "trim" if "start" in edits or "end" in edits else "title_hook_edit"))
    decision = ReviewDecision(candidate_id=candidate_id, action=action, **edits)
    revised = plan.model_copy(update={"decisions": (*plan.decisions, decision), "status": "reviewed"})
    return _save(revised).model_dump(mode="json")


def shorts_review(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Append an explicit human decision without rendering."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    decision_payload = kwargs.pop("decision", None)
    evidence_ref = kwargs.pop("evidence_ref", None)
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    if len(args) > 2:
        decision_payload = args[2]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    payload = dict(decision_payload) if isinstance(decision_payload, dict) else {"action": str(decision_payload)}
    action = payload.pop("action", payload.pop("decision", None))
    if action not in ReviewDecision.model_fields["action"].annotation.__args__:
        raise _error(
            "The review decision is not supported.",
            code="shorts_review_invalid",
            cause=f"Unknown action {action!r}.",
            recovery="Use preview, approve, reject, trim, title_hook_edit, or sensitive_unsuitable.",
        )
    record = ReviewDecision(candidate_id=str(candidate_id), action=action, evidence_ref=evidence_ref, **payload)
    revised = plan.model_copy(update={"decisions": (*plan.decisions, record), "status": "reviewed"})
    saved = _save(revised)
    return {
        "job_id": saved.job_id,
        "proposal_id": candidate_id,
        "decisions": [d.model_dump(mode="json") for d in saved.decisions],
        "status": saved.status,
    }


def _effective_candidate(plan: ShortsPlan, candidate_id: str) -> CandidateMoment:
    candidate = next((item for item in plan.proposals if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise _error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause="Its id is not in the plan.",
            recovery="Choose a candidate from the proposal output.",
        )
    updates: dict[str, Any] = {}
    approved = False
    for decision in plan.decisions:
        if decision.candidate_id != candidate_id:
            continue
        if decision.action == "reject":
            approved = False
        elif decision.action == "approve":
            approved = True
        elif decision.action == "trim":
            updates.update(start=decision.start, end=decision.end)
        elif decision.action == "title_hook_edit":
            if decision.title:
                updates["suggested_title"] = decision.title
            if decision.hook:
                updates["suggested_hook"] = decision.hook
        elif decision.action == "sensitive_unsuitable" and decision.unsuitable:
            updates.update(unsuitable=True, sensitivity="unsafe")
    candidate = candidate.model_copy(update=updates)
    if not approved:
        raise _error(
            "The candidate is not approved for rendering.",
            code="shorts_review_required",
            cause="No current human approval exists.",
            recovery="Record an approve decision after reviewing the candidate.",
        )
    if candidate.unsuitable:
        raise _error(
            "The candidate is marked unsuitable.",
            code="shorts_candidate_unsuitable",
            cause="Human review flagged sensitive material.",
            recovery="Choose another candidate or record a deliberate revised review decision.",
        )
    return candidate


def _caption_for(plan: ShortsPlan, candidate: CandidateMoment):
    overlapping = [s for s in plan.transcript if s.end > candidate.start and s.start < candidate.end]
    words: list[WordTiming] = []
    for segment in overlapping:
        tokens = segment.text.split()
        if not tokens:
            continue
        step = (segment.end - segment.start) / len(tokens)
        for index, token in enumerate(tokens):
            global_start = segment.start + index * step
            global_end = segment.start + (index + 1) * step
            if global_end <= candidate.start or global_start >= candidate.end:
                continue
            word_start = max(global_start, candidate.start) - candidate.start
            word_end = min(global_end, candidate.end) - candidate.start
            words.append(
                WordTiming(
                    word=token,
                    start=word_start,
                    end=max(word_end, word_start + 0.001),
                    probability=segment.confidence or 1.0,
                )
            )
    return build_caption_artifact(words, config=CaptionConfig())


def shorts_render(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Render approved vertical drafts using existing trim/resize/audio engines."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    output_path = kwargs.pop("output_path", None)
    render_options = dict(kwargs.pop("render_options", {}) or {})
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    candidate = _effective_candidate(plan, str(candidate_id))
    base_dir = os.path.realpath(output_path or os.path.join(plan.output_dir, candidate.candidate_id))
    if os.path.splitext(base_dir)[1]:
        base_dir = os.path.dirname(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    records: list[RenderRecord] = list(plan.renders)
    emitted: list[dict[str, Any]] = []
    candidate_digest = hashlib.sha256(
        json.dumps(candidate.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()[:16]
    for platform in plan.platforms:
        platform_dir = os.path.join(base_dir, platform)
        os.makedirs(platform_dir, exist_ok=True)
        final_path = os.path.join(platform_dir, "vertical.mp4")
        digest = hashlib.sha256(
            f"render-v3:{plan.intake.source_sha256}:{candidate_digest}:{platform}:{plan.config}".encode()
        ).hexdigest()[:16]
        previous = next(
            (
                r
                for r in records
                if r.candidate_id == candidate.candidate_id
                and r.platform == platform
                and r.render_digest == digest
                and os.path.exists(r.output_path)
            ),
            None,
        )
        if previous:
            emitted.append(previous.model_copy(update={"cache_hit": True}).model_dump(mode="json"))
            continue
        trimmed = trim(
            plan.intake.source_path,
            start=candidate.start,
            duration=candidate.end - candidate.start,
            output_path=os.path.join(platform_dir, "trimmed.mp4"),
        )
        vertical = resize(
            trimmed.output_path, aspect_ratio="9:16", output_path=os.path.join(platform_dir, "vertical-raw.mp4")
        )
        audio_cfg = plan.config.get("render", {}).get("audio", {})
        normalized = normalize_audio(
            vertical.output_path,
            target_lufs=float(audio_cfg.get("lufs", -14.0)),
            output_path=os.path.join(platform_dir, "vertical-normalized.mp4"),
        )
        fade_seconds = float(audio_cfg.get("fade_seconds", 0.05))
        fade_out_start = max(0.0, candidate.end - candidate.start - fade_seconds)
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                normalized.output_path,
                output_path=final_path,
                video_codec="copy",
                audio_filter=f"afade=t=in:st=0:d={fade_seconds:.3f},afade=t=out:st={fade_out_start:.3f}:d={fade_seconds:.3f}",
            )
        )
        finished_path = final_path
        caption = _caption_for(plan, candidate)
        srt_path = os.path.join(platform_dir, "captions.srt")
        Path(srt_path).write_text(
            caption.srt_body + ("" if caption.srt_body.endswith("\n") else "\n"), encoding="utf-8"
        )
        if plan.config.get("render", {}).get("burned_captions", False):
            burned = subtitles(
                finished_path,
                srt_path,
                output_path=os.path.join(platform_dir, "vertical-burned.mp4"),
            )
            finished_path = burned.output_path
        thumb_path = thumbnail(finished_path, output_path=os.path.join(platform_dir, "thumbnail.jpg")).output_path
        record = RenderRecord(
            candidate_id=candidate.candidate_id,
            platform=platform,
            output_path=finished_path,
            render_digest=digest,
            editable_subtitles=srt_path,
            thumbnail_path=thumb_path,
        )
        records = [r for r in records if not (r.candidate_id == candidate.candidate_id and r.platform == platform)] + [
            record
        ]
        emitted.append(record.model_dump(mode="json"))
    revised = plan.model_copy(update={"renders": tuple(records), "status": "rendered"})
    _save(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "rendered",
        "renders": emitted,
        "external_posting": False,
        "render_options": render_options,
    }


def shorts_package(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Create complete manual-publishing packages for an approved clip."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    package_dir = kwargs.pop("package_dir", None)
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    candidate = _effective_candidate(plan, str(candidate_id))
    relevant = [r for r in plan.renders if r.candidate_id == candidate.candidate_id]
    if not relevant:
        raise _error(
            "No rendered drafts exist for this candidate.",
            code="shorts_render_required",
            cause="Packaging was requested before render completed.",
            recovery="Run shorts_render for the approved candidate first.",
        )
    root = os.path.realpath(package_dir or os.path.join(plan.output_dir, candidate.candidate_id, "packages"))
    manifests: list[str] = list(plan.package_manifests)
    results: list[dict[str, Any]] = []
    for record in relevant:
        target = os.path.join(root, record.platform)
        os.makedirs(target, exist_ok=True)
        packaged_video = os.path.join(target, "vertical.mp4")
        packaged_thumbnail = os.path.join(target, "thumbnail.jpg")
        shutil.copy2(record.output_path, packaged_video)
        shutil.copy2(record.thumbnail_path, packaged_thumbnail)
        caption = _caption_for(plan, candidate)
        result = package_approved_clip(
            package_dir=target,
            vertical_video_path=packaged_video,
            caption_artifact=caption,
            candidate=candidate,
            thumbnail=ThumbnailSpec(image_path=packaged_thumbnail, timestamp=(candidate.end - candidate.start) / 2),
            lineage=PackageLineage(
                candidate_id=candidate.candidate_id,
                transcript_reference=plan.intake.source_sha256,
                review_decision_ref=record.render_digest,
            ),
            config=PackageConfig(overwrite_manifest=True),
        )
        manifests.append(result.manifest_path)
        results.append(result.model_dump(mode="json"))
    revised = plan.model_copy(update={"package_manifests": tuple(dict.fromkeys(manifests)), "status": "packaged"})
    _save(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "packaged",
        "packages": results,
        "external_posting": False,
    }


def load_shorts_plan(job_or_path: str) -> ShortsPlan:
    return _load(job_or_path)


__all__ = [
    "IntakeReport",
    "RenderRecord",
    "ReviewDecision",
    "ShortsPlan",
    "load_shorts_plan",
    "shorts_package",
    "shorts_plan",
    "shorts_propose",
    "shorts_render",
    "shorts_review",
]
