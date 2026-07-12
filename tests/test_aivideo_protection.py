"""Protected-element mutation precheck."""

from __future__ import annotations

import pytest

from kinocut.aivideo.protection import (
    MutationIntent,
    assert_no_protected_collision,
    protect,
    touched_dependencies,
)
from kinocut.contracts.protection import ElementType, ProtectedElement
from kinocut.contracts.review import ReviewDecision
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import protection_kwargs, review_decision_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _element(project, **overrides) -> ProtectedElement:
    return ProtectedElement(**protection_kwargs(project_id=project.project_id, **overrides))


def _mutation_touching(lock: ProtectedElement, **overrides) -> MutationIntent:
    values = {
        "operation": "body_swap",
        "source_asset": "sha256:" + "b" * 64,
        "audio_stream": lock.dependency_fingerprint,
    }
    values.update(overrides)
    return MutationIntent(**values)


def _protected_with_original(project, *, original_created_by="human"):
    fingerprint = "sha256:" + "a" * 64
    original = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                created_by=original_created_by,
                target_ref=fingerprint,
                dependency_fingerprint=fingerprint,
            )
        ),
    )
    lock = protect(project, _element(project, human_approval_ref=original.record_id))
    return lock, original


def test_protected_collision_fails_without_new_human_decision(project):
    lock = protect(project, _element(project))
    op = _mutation_touching(lock)
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(project, op)
    assert excinfo.value.code == "protected_element_change"


def test_explicitly_allowed_operation_does_not_collide(project):
    lock = protect(project, _element(project, allowed_operations=("body_swap",)))
    assert_no_protected_collision(project, _mutation_touching(lock))


def test_new_stored_human_decision_authorizes_collision(project):
    lock, original = _protected_with_original(project)
    decision = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=lock.dependency_fingerprint,
                dependency_fingerprint=lock.dependency_fingerprint,
                source_record_ids=(lock.record_id, original.record_id),
            )
        ),
    )
    op = _mutation_touching(lock, authorization_decision_ids=(decision.record_id,))
    assert_no_protected_collision(project, op)


def test_mutation_intent_has_no_force_path():
    assert "force" not in MutationIntent.model_fields


def test_touched_dependencies_is_a_deduplicated_set():
    source = "sha256:" + "b" * 64
    audio = "sha256:" + "a" * 64
    op = MutationIntent(operation="body_swap", source_asset=source, audio_stream=audio)
    assert touched_dependencies(op) == {
        (ElementType.SOURCE_ASSET, source),
        (ElementType.AUDIO_STREAM, audio),
    }


def test_omitted_footprint_cannot_bypass_known_collision(project):
    protect(project, _element(project))
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            {"operation": "body_swap", "source_asset": "sha256:" + "b" * 64},
        )
    assert excinfo.value.code == "invalid_mutation_intent"


def test_empty_footprint_cannot_bypass_known_collision(project):
    protect(project, _element(project))
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            {"operation": "body_swap", "source_asset": "", "audio_stream": ""},
        )
    assert excinfo.value.code == "invalid_mutation_intent"


def test_arbitrary_footprint_and_unknown_operation_fail_closed(project):
    protect(project, _element(project))
    arbitrary = {
        "operation": "body_swap",
        "dependency_fingerprints": ("sha256:" + "b" * 64,),
    }
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(project, arbitrary)
    assert excinfo.value.code == "invalid_mutation_intent"
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            {"operation": "custom", "source_asset": "sha256:" + "b" * 64},
        )
    assert excinfo.value.code == "invalid_mutation_intent"


def test_different_exact_target_does_not_collide(project):
    protect(project, _element(project))
    operation = MutationIntent(
        operation="body_swap",
        source_asset="sha256:" + "b" * 64,
        audio_stream="sha256:" + "c" * 64,
    )
    assert_no_protected_collision(project, operation)


def test_agent_authored_original_approval_cannot_authorize_change(project):
    lock, original = _protected_with_original(project, original_created_by="agent")
    decision = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=lock.dependency_fingerprint,
                dependency_fingerprint=lock.dependency_fingerprint,
                source_record_ids=(lock.record_id, original.record_id),
            )
        ),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            _mutation_touching(lock, authorization_decision_ids=(decision.record_id,)),
        )
    assert excinfo.value.code == "protected_element_change"


def test_agent_authored_new_approval_cannot_authorize_change(project):
    lock, original = _protected_with_original(project)
    decision = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                created_by="agent",
                target_ref=lock.dependency_fingerprint,
                dependency_fingerprint=lock.dependency_fingerprint,
                source_record_ids=(lock.record_id, original.record_id),
            )
        ),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            _mutation_touching(lock, authorization_decision_ids=(decision.record_id,)),
        )
    assert excinfo.value.code == "protected_element_change"


def test_unrelated_preexisting_approval_cannot_authorize_change(project):
    lock, _original = _protected_with_original(project)
    unrelated = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=lock.dependency_fingerprint,
                dependency_fingerprint=lock.dependency_fingerprint,
                rationale="unrelated earlier approval",
            )
        ),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            _mutation_touching(lock, authorization_decision_ids=(unrelated.record_id,)),
        )
    assert excinfo.value.code == "protected_element_change"


def test_two_protected_dependencies_of_same_kind_are_exact_target_scoped(project):
    first = protect(
        project,
        _element(project, allowed_operations=("body_swap",)),
    )
    protect(
        project,
        _element(project, dependency_fingerprint="sha256:" + "c" * 64),
    )
    assert_no_protected_collision(project, _mutation_touching(first))


_ELEMENT_OPERATION_CASES = (
    (ElementType.SOURCE_ASSET, "replace_source", "source_asset"),
    (ElementType.AUDIO_STREAM, "normalize_audio", "audio_stream"),
    (ElementType.CLIP_RANGE, "trim_clip", "clip_range"),
    (ElementType.TIMELINE_RANGE, "edit_timeline", "timeline_range"),
    (ElementType.GRAPHIC, "edit_graphic", "graphic"),
    (ElementType.SUBTITLE_SET, "edit_subtitles", "subtitle_set"),
    (ElementType.TIMING_MAP, "retime", "timing_map"),
    (ElementType.MIX, "remix", "mix"),
    (
        ElementType.RENDER_PARAMETER_SET,
        "change_render_parameters",
        "render_parameter_set",
    ),
)


@pytest.mark.parametrize(("element_type", "operation", "field"), _ELEMENT_OPERATION_CASES)
def test_every_element_kind_participates_in_exact_footprint(
    project,
    element_type,
    operation,
    field,
):
    lock = protect(project, _element(project, element_type=element_type))
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            {"operation": operation, field: lock.dependency_fingerprint},
        )
    assert excinfo.value.code == "protected_element_change"


def test_unrelated_element_kind_does_not_collide(project):
    protect(project, _element(project, element_type="graphic"))
    assert_no_protected_collision(
        project,
        {
            "operation": "normalize_audio",
            "audio_stream": "sha256:" + "a" * 64,
        },
    )


def test_operation_that_cannot_derive_complete_footprint_fails_closed(project):
    protect(project, _element(project))
    with pytest.raises(MCPVideoError) as excinfo:
        assert_no_protected_collision(
            project,
            {
                "operation": "body_swap",
                "source_asset": "sha256:" + "b" * 64,
                "graphic": "sha256:" + "c" * 64,
            },
        )
    assert excinfo.value.code == "invalid_mutation_intent"
