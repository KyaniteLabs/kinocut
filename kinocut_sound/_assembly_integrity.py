"""Private canonical-integrity checks for episode assemblies."""

from __future__ import annotations

from typing import Any

from kinocut_sound.timeline import CueKind


def validate_episode_assembly(value: Any) -> None:
    """Reject contradictory line, route, clip, and Foley artifact bindings."""
    route_cue_ids = tuple(route.cue_id for route in value.routes)
    route_line_ids = tuple(route.line_id for route in value.routes)
    line_cue_ids = tuple(cue.cue_id for cue in value.timeline.cues if cue.kind == CueKind.LINE)
    foley_cue_ids = tuple(cue.cue_id for cue in value.timeline.cues if cue.kind == CueKind.FOLEY)

    if route_cue_ids != value.line_cue_order:
        raise ValueError("route order must match line cue order")
    if route_line_ids != value.line_ids or len(set(route_line_ids)) != len(route_line_ids):
        raise ValueError("route line ids must exactly match unique assembly line ids")
    line_counts = {
        len(value.line_ids),
        len(value.line_cue_order),
        len(value.routes),
        len(value.clip_hashes),
        len(line_cue_ids),
    }
    if len(line_counts) != 1 or line_cue_ids != value.line_cue_order:
        raise ValueError("line cues, routes, ids, and clip hashes must bind one-to-one")
    if foley_cue_ids != value.foley_cue_ids or len(value.foley_hashes) != len(value.foley_cue_ids):
        raise ValueError("Foley cue ids and hashes must bind in timeline order")
    if value.parsed_script_id not in value.source_record_ids:
        raise ValueError("parsed script id must be a source record id")
