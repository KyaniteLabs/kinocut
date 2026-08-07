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
) -> dict[str, Any]:
    """Route a semantic intent verb to a plan (does not silently mutate media)."""

    from kinocut.intent import list_intent_verbs, route_intent

    if list_verbs:
        return _result({"artifact_kind": "intent_catalog", "verbs": list_intent_verbs()})
    plan = route_intent(verb, params)
    return _result({"artifact_kind": "intent_plan", **plan.to_dict()})


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
) -> dict[str, Any]:
    """Record human accept/reject/revise on a review_run artifact."""

    from kinocut.watching import decide_review

    return _result(decide_review(review_run, decision, reason).to_dict())


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
def video_cutfile_validate(path: str) -> dict[str, Any]:
    """Validate a text-first Cutfile (v1 JSON or minimal YAML scaffold)."""

    from kinocut.te import load_cutfile

    cf = load_cutfile(path)
    return _result(cf.to_dict())
