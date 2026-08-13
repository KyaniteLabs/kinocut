"""Small durable intent-verb surface over projectstore."""

from __future__ import annotations

from typing import Any

from kinocut.projectstore import find_moments, open_project, persist_moment_selection, persist_semantic_index
from kinocut.semantic.index import SemanticIndex, build_semantic_index
from kinocut.semantic.models import SemanticTimeline

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_find_moments(
    project_dir: str,
    edit_project_id: str,
    revision_id: str,
    text: str | None = None,
    index_digest: str | None = None,
    semantic_artifact: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
    limit: int = 10,
    min_confidence: float = 0.0,
    selected_span_ids: list[str] | None = None,
    selection_example_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Persist or query a revision-bound local semantic index."""

    project = open_project(project_dir)
    if (index_digest is None) == (semantic_artifact is None):
        from kinocut.errors import ValidationError

        raise ValidationError("index", "provide exactly one of index_digest or semantic_artifact")
    if semantic_artifact is not None:
        if semantic_artifact.get("artifact_kind") == "semantic_timeline":
            index = build_semantic_index(SemanticTimeline.model_validate(semantic_artifact))
        else:
            index = SemanticIndex.model_validate(semantic_artifact)
        record = persist_semantic_index(project, edit_project_id, revision_id, index)
        index_digest = record.index_digest
    hits = find_moments(
        project,
        edit_project_id,
        revision_id,
        index_digest,
        text=text,
        embedding=tuple(embedding) if embedding is not None else None,
        limit=limit,
        min_confidence=min_confidence,
    )
    selection = None
    if selected_span_ids is not None:
        selection = persist_moment_selection(
            project,
            edit_project_id,
            revision_id,
            index_digest,
            hits,
            tuple(selected_span_ids),
            query_text=text,
            selection_example_ids=tuple(selection_example_ids or ()),
        )
    return _result(
        {
            "artifact_kind": "moment_search",
            "edit_project_id": edit_project_id,
            "revision_id": revision_id,
            "index_digest": index_digest,
            "results": [hit.model_dump(mode="json") for hit in hits],
            "selection_record_id": selection.record_id if selection is not None else None,
        }
    )


@mcp.tool()
@_safe_tool
def video_project_recipe_export(
    project_dir: str,
    edit_project_id: str,
    revision_id: str,
    operations: list[dict[str, Any]],
    intent_verb: str = "repurpose",
    policies: list[str] | None = None,
    required_checks: list[str] | None = None,
    review_gates: list[str] | None = None,
) -> dict[str, Any]:
    """Export a verified edit revision as a path-free portable recipe."""

    from kinocut.aivideo.learning.project_recipes import export_project_recipe

    project = open_project(project_dir)
    return _result(
        export_project_recipe(
            project,
            edit_project_id,
            revision_id,
            operations,
            intent_verb=intent_verb,
            policies=tuple(policies or ()),
            required_checks=tuple(required_checks or ()),
            review_gates=tuple(review_gates or ()),
        )
    )


@mcp.tool()
@_safe_tool
def video_project_recipe_replay(
    project_dir: str,
    edit_project_id: str,
    artifact: dict[str, Any],
    source_bindings: dict[str, str],
    base_revision_id: str | None = None,
) -> dict[str, Any]:
    """Replay a portable recipe into a new durable project revision."""

    from kinocut.aivideo.learning.project_recipes import replay_project_recipe

    project = open_project(project_dir)
    return _result(
        replay_project_recipe(
            project,
            edit_project_id,
            artifact,
            source_bindings,
            base_revision_id=base_revision_id,
        )
    )


@mcp.tool()
@_safe_tool
def video_intent(
    verb: str,
    params: dict[str, Any] | None = None,
    list_verbs: bool = False,
    goal: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Route a semantic intent verb to a plan (does not silently mutate media).

    Optional ``goal`` compiles a reviewable cutfile (N1) without rendering.
    """

    from kinocut.intent import list_intent_verbs, route_intent

    if list_verbs:
        return _result({"artifact_kind": "intent_catalog", "verbs": list_intent_verbs()})
    plan = route_intent(verb, params)
    payload: dict[str, Any] = {"artifact_kind": "intent_plan", **plan.to_dict()}
    if goal:
        from kinocut.te import compile_goal_to_cutfile

        payload["cutfile"] = compile_goal_to_cutfile(goal, source=source or "media/hero.mp4")
        payload["next_action"] = "review_then_cutfile_render"
    return _result(payload)


@mcp.tool()
@_safe_tool
def video_propose_broll(
    segments: list[dict[str, Any]],
    max_proposals: int = 8,
    min_span_seconds: float = 0.8,
    keyword_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Transcript-keyed b-roll proposals — human review required, never silent insert."""

    from kinocut.intent import propose_broll

    proposals = propose_broll(
        segments,
        max_proposals=max_proposals,
        min_span_seconds=min_span_seconds,
        keyword_allowlist=keyword_allowlist,
    )
    return _result(
        {
            "artifact_kind": "broll_proposals",
            "apply_policy": "human_review_required",
            "proposal_count": len(proposals),
            "proposals": [p.to_dict() for p in proposals],
        }
    )


@mcp.tool()
@_safe_tool
def video_translate_captions(
    input_path: str,
    output_path: str | None = None,
    source_lang: str = "en",
    target_lang: str = "es",
) -> dict[str, Any]:
    """Translate SRT captions with honest language-coverage reporting (EN→ES first)."""

    from kinocut.intent import translate_caption_file

    result = translate_caption_file(
        input_path,
        output_path,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    return _result(result.to_dict())


@mcp.tool()
@_safe_tool
def video_language_coverage() -> dict[str, Any]:
    """Honest per-surface language coverage for transcribe/translate/dub."""

    from kinocut.intent import language_coverage_report

    return _result(language_coverage_report())


@mcp.tool()
@_safe_tool
def video_review_run(
    input_path: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Watching guardrail: run offline metric floor under a review policy."""

    from kinocut.watching import ReviewPolicy, run_review

    pol = ReviewPolicy(**policy) if policy else ReviewPolicy()
    return _result(run_review(input_path, pol).to_dict())


@mcp.tool()
@_safe_tool
def video_review_decide(
    review_run: dict[str, Any],
    decision: str,
    reason: str = "",
    input_path: str | None = None,
    output_path: str | None = None,
    edl: dict[str, Any] | None = None,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record human accept/reject/revise. Accept + EDL approval can render (N4)."""

    from kinocut.watching import decide_review

    decided = decide_review(review_run, decision, reason).to_dict()
    if (decision or "").lower() == "accept" and input_path and output_path and edl and approval:
        from kinocut.te import render_approved_edl

        decided["edl_render"] = render_approved_edl(
            input_path, edl=edl, approval=approval, output_path=output_path
        )
    return _result(decided)


@mcp.tool()
@_safe_tool
def video_propose_mutations(
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map QC findings to typed proposed mutations (human apply only)."""

    from kinocut.watching import propose_mutations_from_findings

    props = propose_mutations_from_findings(findings)
    return _result(
        {
            "artifact_kind": "proposed_mutations",
            "apply_policy": "human_review_required",
            "mutation_count": len(props),
            "mutations": [p.to_dict() for p in props],
        }
    )


@mcp.tool()
@_safe_tool
def video_init_project(
    path: str,
    name: str | None = None,
    with_cutfile: bool = True,
) -> dict[str, Any]:
    """Scaffold a local Kinocut project directory (media/out/receipts + optional Cutfile)."""

    from kinocut.te import init_project

    return _result(init_project(path, name=name, with_cutfile=with_cutfile))


@mcp.tool()
@_safe_tool
def video_brand_kit(
    action: str,
    path: str,
    kit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save or load a brand kit / style profile JSON."""

    from kinocut.te import BrandKit, load_brand_kit, save_brand_kit

    act = (action or "").strip().lower()
    if act == "save":
        if not kit:
            from kinocut.errors import MCPVideoError

            raise MCPVideoError(
                "kit object required for save",
                error_type="validation_error",
                code="brand_kit_required",
            )
        model = BrandKit(
            name=str(kit.get("name") or "brand"),
            primary_color=str(kit.get("primary_color") or "#FFFFFF"),
            accent_color=str(kit.get("accent_color") or "#000000"),
            font=str(kit.get("font") or "sans"),
            logo_path=kit.get("logo_path"),
            subtitle_style=dict(kit.get("subtitle_style") or {}),
            notes=str(kit.get("notes") or ""),
        )
        return _result(save_brand_kit(path, model))
    if act == "load":
        return _result({"artifact_kind": "brand_kit", **load_brand_kit(path).to_dict()})
    from kinocut.errors import MCPVideoError

    raise MCPVideoError(
        "action must be save|load",
        error_type="validation_error",
        code="invalid_brand_kit_action",
    )


@mcp.tool()
@_safe_tool
def video_estimate_operation(
    operation: str,
    duration_seconds: float,
    complexity: float = 1.0,
) -> dict[str, Any]:
    """Dry-run local wall-time / cost-unit estimate (not cloud pricing)."""

    from kinocut.te import estimate_operation

    return _result(estimate_operation(operation, duration_seconds=duration_seconds, complexity=complexity))


@mcp.tool()
@_safe_tool
def video_cutfile_validate(
    path: str | None = None,
    goal: str | None = None,
    source: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Validate a Cutfile, or compile one from ``goal`` / ``platform`` (N1/N5)."""

    from kinocut.te import compile_goal_to_cutfile, load_cutfile, solve_publish_cutfile

    if platform:
        return _result(solve_publish_cutfile(platform, source=source or "media/hero.mp4"))
    if goal:
        return _result(compile_goal_to_cutfile(goal, source=source or "media/hero.mp4"))
    if not path:
        from kinocut.errors import MCPVideoError

        raise MCPVideoError("path, goal, or platform required", error_type="validation_error", code="cutfile_args")
    cf = load_cutfile(path)
    return _result(cf.to_dict())


@mcp.tool()
@_safe_tool
def video_cutfile_render(
    path: str,
    output_path: str | None = None,
    save_receipt: str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    """Render a schema-valid Cutfile via the workflow engine (Track E)."""

    from kinocut.te import render_cutfile

    return _result(
        render_cutfile(
            path,
            output_path=output_path,
            save_receipt=save_receipt,
            keep_intermediates=keep_intermediates,
        )
    )


@mcp.tool()
@_safe_tool
def video_metric_qc(
    input_path: str,
    min_duration_seconds: float = 0.5,
    max_black_ratio: float = 0.95,
) -> dict[str, Any]:
    """Offline metric floor (duration/black/loudness) — fail-closed, no invented values."""

    from kinocut.watching import run_metric_qc

    findings = run_metric_qc(
        input_path,
        min_duration_seconds=min_duration_seconds,
        max_black_ratio=max_black_ratio,
    )
    return _result(
        {
            "artifact_kind": "metric_qc",
            "finding_count": len(findings),
            "findings": [f.to_dict() for f in findings],
            "fail_count": sum(1 for f in findings if f.severity == "fail"),
        }
    )


@mcp.tool()
@_safe_tool
def video_timeline_ir_validate(timeline: dict[str, Any]) -> dict[str, Any]:
    """Validate Timeline IR and compile to render DAG (P3.0).

    Semantic timelines (shots/silences/words) also get agent-visible ``text`` (N2).
    """

    from kinocut.te import render_timeline_text
    from kinocut.timeline_ir import compile_ir_to_dag, ir_identity, parse_timeline_ir

    view = None
    if any(timeline.get(k) for k in ("shots", "silences", "words", "scenes")):
        try:
            view = render_timeline_text(timeline)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).debug("timeline text skipped: %s", exc)
            view = None
    if timeline.get("ir_schema_version") or timeline.get("nodes"):
        ir = parse_timeline_ir(timeline)
        dag = compile_ir_to_dag(ir)
        payload = {
            "artifact_kind": "timeline_ir",
            "identity": ir_identity(ir),
            "ir": ir.model_dump(mode="json"),
            "dag_node_count": len(getattr(dag, "nodes", []) or []),
            "compiled": True,
        }
        if view:
            payload["text"] = view.get("text")
            payload["timeline_view"] = view
        return _result(payload)
    if view:
        return _result(view)
    ir = parse_timeline_ir(timeline)
    dag = compile_ir_to_dag(ir)
    return _result(
        {
            "artifact_kind": "timeline_ir",
            "identity": ir_identity(ir),
            "ir": ir.model_dump(mode="json"),
            "dag_node_count": len(getattr(dag, "nodes", []) or []),
            "compiled": True,
        }
    )


@mcp.tool()
@_safe_tool
def video_qc_vision(input_path: str, require_vlm: bool = False) -> dict[str, Any]:
    """Vision QC third — graceful if VLM unavailable (P3.3)."""

    from kinocut.watching import run_vision_qc

    return _result(run_vision_qc(input_path, require_vlm=require_vlm))


@mcp.tool()
@_safe_tool
def video_qc_narrative(input_path: str) -> dict[str, Any]:
    """Narrative/retention heuristics incl. first-15s window (P3.4)."""

    from kinocut.watching import run_narrative_qc

    return _result(run_narrative_qc(input_path))


@mcp.tool()
@_safe_tool
def video_generative_plan(
    prompt: str,
    provider: str = "local",
    model: str | None = None,
    max_spend_usd: float = 0.0,
    estimated_spend_usd: float = 0.0,
) -> dict[str, Any]:
    """Generative last-mile plan with spend caps (P4.1) — plan only.

    Paid providers require ``max_spend_usd > 0`` and estimate ≤ cap.
    Use ``assert_generative_executable`` (multipliers) before any provider I/O.
    """

    from kinocut.multipliers import plan_generative_last_mile

    return _result(
        plan_generative_last_mile(
            prompt,
            provider=provider,
            model=model,
            max_spend_usd=max_spend_usd,
            estimated_spend_usd=estimated_spend_usd,
        ).to_dict()
    )


@mcp.tool()
@_safe_tool
def video_otio_export(timeline: dict[str, Any], output_path: str) -> dict[str, Any]:
    """Export Timeline IR to simplified OTIO JSON (P4.2)."""

    from kinocut.multipliers import export_otio_json

    return _result(export_otio_json(timeline, output_path))


@mcp.tool()
@_safe_tool
def video_otio_import(path: str) -> dict[str, Any]:
    """Import simplified OTIO JSON to Timeline IR (P4.2)."""

    from kinocut.multipliers import import_otio_json

    return _result(import_otio_json(path))


@mcp.tool()
@_safe_tool
def video_review_ui(output_dir: str) -> dict[str, Any]:
    """Write hot-reloading human review HTML surface (P4.3)."""

    from kinocut.multipliers import write_review_surface

    return _result(write_review_surface(output_dir))


@mcp.tool()
@_safe_tool
def video_dub_plan(caption_path: str, target_lang: str = "es", voice: str | None = None) -> dict[str, Any]:
    """Local TTS dub plan ES-first (P4.4) — plan only until backend configured."""

    from kinocut.multipliers import plan_tts_dub

    return _result(plan_tts_dub(caption_path, target_lang=target_lang, voice=voice))


@mcp.tool()
@_safe_tool
def video_publish_validate(
    platform: str,
    duration_seconds: float,
    height: int,
    width: int,
    container: str = "mp4",
    solve: bool = False,
    source: str | None = None,
    captions: bool = False,
) -> dict[str, Any]:
    """Validate a publish spec. ``solve=True`` also emits a cutfile (N5)."""

    from kinocut.te import solve_publish_cutfile, validate_publish_spec

    if solve:
        return _result(
            solve_publish_cutfile(
                platform,
                source=source or "media/hero.mp4",
                source_duration=duration_seconds or 60.0,
                captions=captions,
            )
        )
    return _result(
        validate_publish_spec(
            platform,
            duration_seconds=duration_seconds,
            height=height,
            width=width,
            container=container,
        )
    )


@mcp.tool()
@_safe_tool
def video_hook_candidates(topic: str, count: int = 5, language: str = "en") -> dict[str, Any]:
    """Thumbnail + hook-title candidates for human pick (TE.2)."""

    from kinocut.te import generate_hook_candidates

    return _result(generate_hook_candidates(topic, count=count, language=language))


@mcp.tool()
@_safe_tool
def video_audiogram_plan(
    audio_path: str,
    width: int = 1080,
    height: int = 1080,
    chapter_marks: list[float] | None = None,
) -> dict[str, Any]:
    """Audiogram + chapter mark plan (TE.4)."""

    from kinocut.te import plan_audiogram

    return _result(plan_audiogram(audio_path, width=width, height=height, chapter_marks=chapter_marks))


@mcp.tool()
@_safe_tool
def video_punch_zoom_plan(cut_times: list[float], zoom: float = 1.15, duration_seconds: float = 0.35) -> dict[str, Any]:
    """Auto-zoom punch-in plan on cut points (TE.5)."""

    from kinocut.te import plan_punch_zooms

    return _result(plan_punch_zooms(cut_times, zoom=zoom, duration_seconds=duration_seconds))


@mcp.tool()
@_safe_tool
def video_seek_frame(frame: int | None = None, seconds: float | None = None, fps: float = 30.0) -> dict[str, Any]:
    """Frame-accurate seek conversion (TE.9)."""

    from kinocut.errors import MCPVideoError
    from kinocut.te import frame_to_timestamp, timestamp_to_frame

    if frame is not None:
        return _result(frame_to_timestamp(int(frame), fps))
    if seconds is not None:
        return _result(timestamp_to_frame(float(seconds), fps))
    raise MCPVideoError("provide frame or seconds", error_type="validation_error", code="seek_args")


@mcp.tool()
@_safe_tool
def video_edit_session(
    action: str,
    path: str,
    goal: str | None = None,
    step_action: str | None = None,
    score: float | None = None,
    notes: str = "",
    input_path: str | None = None,
) -> dict[str, Any]:
    """Conversational edit session. Step with ``input_path`` measures real QC (N6)."""

    from kinocut.errors import MCPVideoError
    from kinocut.te import session_close, session_open, session_step

    act = (action or "").lower()
    if act == "open":
        return _result(session_open(path, goal or "edit"))
    if act == "step":
        return _result(
            session_step(
                path,
                action=step_action or "step",
                score=score,
                notes=notes,
                input_path=input_path,
            )
        )
    if act == "close":
        return _result(session_close(path))
    raise MCPVideoError("action must be open|step|close", error_type="validation_error", code="session_action")
