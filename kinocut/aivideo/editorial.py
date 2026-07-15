"""Editorial planning engines: beat map writer/query (#42).

A beat map is canonical, append-only state bound to one acceptance spec. The
writer rejects a map whose acceptance spec is absent (dangling reference); the
query returns active (non-superseded) maps for a spec.
"""

from __future__ import annotations

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.editorial import BeatMap
from kinocut.projectstore import Project, append_record, read_records


def _active(project: Project, kind: str, model: type) -> list[object]:
    rows = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def _spec_exists(project: Project, spec_id: str) -> bool:
    rows = read_records(project, "generation_acceptance_spec")
    return any(type(item) is GenerationAcceptanceSpec and item.record_id == spec_id for item in rows)


def record_beat_map(project: Project, beat_map: BeatMap) -> BeatMap:
    """Persist one beat map, rejecting a dangling acceptance-spec reference."""

    if not _spec_exists(project, beat_map.acceptance_spec_id):
        raise contract_error("beat map references no acceptance spec", INVALID_RECORD)
    return append_record(project, beat_map)  # type: ignore[return-value]


def beat_maps_for_spec(project: Project, spec_id: str) -> list[BeatMap]:
    """Return active beat maps bound to ``spec_id``."""

    return [item for item in _active(project, "beat_map", BeatMap) if item.acceptance_spec_id == spec_id]  # type: ignore[return-value]


__all__ = ["beat_maps_for_spec", "record_beat_map"]
