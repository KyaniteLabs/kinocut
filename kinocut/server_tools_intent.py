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
