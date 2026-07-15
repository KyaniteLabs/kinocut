"""Beat map: planned beat requirements bound to an acceptance spec (#42)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.editorial import beat_maps_for_spec, record_beat_map
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.editorial import BeatMap, BeatRequirement
from kinocut.errors import MCPVideoError
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


def test_record_beat_map_persists_bound_to_acceptance_spec(project):
    spec = append_record(project, _spec(project))
    stored = record_beat_map(project, _beat_map(project, spec.record_id))
    assert stored.record_kind == "beat_map"
    assert stored.acceptance_spec_id == spec.record_id
    assert [b.beat_id for b in stored.beats] == ["intro", "demo"]
    assert stored.record_id == canonical_record_id(_beat_map(project, spec.record_id))


def test_record_beat_map_rejects_dangling_acceptance_spec(project):
    with pytest.raises(MCPVideoError, match="acceptance spec"):
        record_beat_map(project, _beat_map(project, "sha256:" + "0" * 64))


def test_beat_maps_for_spec_returns_active_only(project):
    spec = append_record(project, _spec(project))
    first = record_beat_map(project, _beat_map(project, spec.record_id))
    record_beat_map(
        project,
        _beat_map(
            project,
            spec.record_id,
            supersedes=first.record_id,
            beats=(BeatRequirement(beat_id="intro", label="Revised open"),),
        ),
    )
    rows = beat_maps_for_spec(project, spec.record_id)
    assert len(rows) == 1
    assert rows[0].beats[0].label == "Revised open"


def test_beat_map_rejects_duplicate_beat_ids(project):
    spec = append_record(project, _spec(project))
    with pytest.raises(Exception, match="unique"):
        record_beat_map(
            project,
            _beat_map(
                project,
                spec.record_id,
                beats=(
                    BeatRequirement(beat_id="intro", label="A"),
                    BeatRequirement(beat_id="intro", label="B"),
                ),
            ),
        )
