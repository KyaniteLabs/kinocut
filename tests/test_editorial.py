"""Beat map and continuity plan contract validation."""

from __future__ import annotations

import pytest

from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.editorial import BeatMap, BeatRequirement, ContinuityExpectation, ContinuityPlan
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import acceptance_spec_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _spec(project, **overrides) -> GenerationAcceptanceSpec:
    return GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project.project_id, **overrides))


def _beat_map(project, spec_id, **overrides) -> BeatMap:
    base = {
        "project_id": project.project_id,
        "created_by": "human",
        "acceptance_spec_id": spec_id,
        "beats": (
            BeatRequirement(beat_id="intro", label="Cold open", required_subjects=("product",)),
            BeatRequirement(beat_id="demo", label="Product demo"),
        ),
    }
    base.update(overrides)
    return BeatMap(**base)


def test_beat_map_rejects_duplicate_beat_ids(project):
    spec = append_record(project, _spec(project))
    with pytest.raises(Exception, match="unique"):
        _beat_map(
            project,
            spec.record_id,
            beats=(
                BeatRequirement(beat_id="intro", label="A"),
                BeatRequirement(beat_id="intro", label="B"),
            ),
        )


def _continuity_plan(project, spec_id, **overrides) -> ContinuityPlan:
    base = {
        "project_id": project.project_id,
        "created_by": "human",
        "acceptance_spec_id": spec_id,
        "expectations": (
            ContinuityExpectation(shot_id="shot_a", expected_subjects=("product",)),
            ContinuityExpectation(shot_id="shot_b", forbidden_changes=("wardrobe",)),
        ),
    }
    base.update(overrides)
    return ContinuityPlan(**base)


def test_continuity_plan_rejects_duplicate_shot_ids(project):
    spec = append_record(project, _spec(project))
    with pytest.raises(Exception, match="unique"):
        _continuity_plan(
            project,
            spec.record_id,
            expectations=(
                ContinuityExpectation(shot_id="shot_a"),
                ContinuityExpectation(shot_id="shot_a"),
            ),
        )
