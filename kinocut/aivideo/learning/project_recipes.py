"""Portable recipes derived from verified projectstore revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.learning import ParameterSlot, WorkflowRecipe
from kinocut.contracts.trusted_execution import EditRevisionRecord
from kinocut.projectstore import Project, compile_operations, compile_repurpose_slice, read_records

from .recipes import record_workflow_recipe

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_FIELDS = frozenset({"source", "sources", "subtitle"})


def _revision(project: Project, edit_project_id: str, revision_id: str) -> EditRevisionRecord:
    matches = [
        record
        for record in read_records(project, "edit_revision")
        if isinstance(record, EditRevisionRecord)
        and record.edit_project_id == edit_project_id
        and record.record_id == revision_id
    ]
    if len(matches) != 1:
        raise contract_error("recipe revision is not owned by the edit project", INVALID_RECORD)
    return matches[0]


def _portable_operations(operations: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    slots: dict[str, str] = {}

    def replace(value: Any) -> Any:
        if isinstance(value, str) and _DIGEST_RE.fullmatch(value):
            name = slots.setdefault(value, f"source_{len(slots) + 1}")
            return "${" + name + "}"
        if isinstance(value, (list, tuple)):
            return [replace(item) for item in value]
        return value

    portable = []
    for operation in operations:
        portable.append(
            {
                key: replace(value) if key in _SOURCE_FIELDS else value
                for key, value in operation.items()
            }
        )
    return portable, tuple(slots.values())


def _canonical_artifact(payload: dict[str, Any]) -> tuple[str, str]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return encoded, "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def export_project_recipe(
    project: Project,
    edit_project_id: str,
    revision_id: str,
    operations: Sequence[Mapping[str, Any]],
    *,
    intent_verb: str = "repurpose",
    policies: Sequence[str] = (),
    required_checks: Sequence[str] = (),
    review_gates: Sequence[str] = (),
) -> dict[str, Any]:
    """Verify descriptors against a revision and export a path-free recipe."""

    revision = _revision(project, edit_project_id, revision_id)
    if compile_operations(operations) != revision.operation_ids:
        raise contract_error("recipe operations do not match the project revision", INVALID_RECORD)
    portable_operations, slot_names = _portable_operations(operations)
    template_payload = {
        "format": "kinocut-recipe",
        "version": 1,
        "intent_verb": intent_verb,
        "operations": portable_operations,
    }
    template, portable_sha256 = _canonical_artifact(template_payload)
    recipe = WorkflowRecipe(
        project_id=project.project_id,
        created_by="tool:recipe_export",
        source_record_ids=(revision.record_id,),
        recipe_version=1,
        template=template,
        parameter_slots=tuple(ParameterSlot(name=name, type="cas_digest") for name in slot_names),
        policies=tuple(policies),
        required_checks=tuple(required_checks),
        review_gates=tuple(review_gates),
    )
    stored = record_workflow_recipe(project, recipe)
    artifact = {
        "format": "kinocut-recipe-export",
        "version": 1,
        "portable_sha256": portable_sha256,
        "template": template_payload,
        "parameter_slots": [slot.model_dump(mode="json") for slot in stored.parameter_slots],
        "policies": list(stored.policies),
        "required_checks": list(stored.required_checks),
        "review_gates": list(stored.review_gates),
    }
    return {
        "recipe_record_id": stored.record_id,
        "source_revision_id": revision.record_id,
        "portable_sha256": portable_sha256,
        "artifact": artifact,
    }


def _replay_operations(template: dict[str, Any], bindings: Mapping[str, str]) -> list[dict[str, Any]]:
    def replace(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            name = value[2:-1]
            digest = bindings.get(name)
            if digest is None or _DIGEST_RE.fullmatch(digest) is None:
                raise contract_error(f"recipe binding {name!r} must be a CAS digest", INVALID_RECORD)
            return digest
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    operations = template.get("operations")
    if not isinstance(operations, list):
        raise contract_error("recipe template operations are invalid", INVALID_RECORD)
    return [replace(operation) for operation in operations]


def replay_project_recipe(
    project: Project,
    edit_project_id: str,
    artifact: Mapping[str, Any],
    source_bindings: Mapping[str, str],
    *,
    base_revision_id: str | None = None,
) -> dict[str, Any]:
    """Validate, persist, and replay one portable recipe against a project."""

    if artifact.get("format") != "kinocut-recipe-export" or artifact.get("version") != 1:
        raise contract_error("recipe artifact format is invalid", INVALID_RECORD)
    template = artifact.get("template")
    if not isinstance(template, dict):
        raise contract_error("recipe artifact template is invalid", INVALID_RECORD)
    template_json, portable_sha256 = _canonical_artifact(template)
    if artifact.get("portable_sha256") != portable_sha256:
        raise contract_error("recipe artifact identity does not match its content", INVALID_RECORD)
    operations = _replay_operations(template, source_bindings)
    revision = compile_repurpose_slice(
        project,
        edit_project_id,
        operations,
        base_revision_id=base_revision_id,
    )
    recipe = WorkflowRecipe(
        project_id=project.project_id,
        created_by="tool:recipe_replay",
        recipe_version=1,
        template=template_json,
        parameter_slots=tuple(ParameterSlot.model_validate(slot) for slot in artifact.get("parameter_slots", ())),
        policies=tuple(artifact.get("policies", ())),
        required_checks=tuple(artifact.get("required_checks", ())),
        review_gates=tuple(artifact.get("review_gates", ())),
    )
    stored = record_workflow_recipe(project, recipe)
    return {
        "recipe_record_id": stored.record_id,
        "portable_sha256": portable_sha256,
        "replay_revision_id": revision.record_id,
        "operation_ids": list(revision.operation_ids),
    }


__all__ = ["export_project_recipe", "replay_project_recipe"]
