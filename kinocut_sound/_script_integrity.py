"""Private cross-record integrity checks for parsed sound scripts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from kinocut_sound._timeline_identity import timeline_emitting_ids


def validate_target_id_uniqueness(
    *,
    parsed_lines: Sequence[Any],
    beats: Sequence[Any],
    chapter_cards: Sequence[Any],
) -> None:
    """Reject duplicate ids within or across parsed target types."""
    target_ids = tuple(item.line.line_id for item in parsed_lines)
    target_ids += tuple(item.beat_id for item in beats)
    target_ids += tuple(item.chapter_id for item in chapter_cards)
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("parsed target ids must be globally unique")


def validate_script_relationships(
    *,
    scenes: Sequence[Any],
    parsed_lines: Sequence[Any],
    beats: Sequence[Any],
    chapter_cards: Sequence[Any],
    events: Sequence[Any],
) -> None:
    """Reject cross-object ownership and event-type inconsistencies."""
    cue_ids = timeline_emitting_ids(scenes=scenes, parsed_lines=parsed_lines, beats=beats)
    if len(cue_ids) != len(set(cue_ids)):
        raise ValueError("timeline-emitting ids must be globally unique")
    targets = {item.line.line_id: ("line", item.scene_id) for item in parsed_lines}
    targets.update({item.beat_id: ("beat", item.scene_id) for item in beats})
    targets.update({item.chapter_id: ("chapter_card", item.scene_id) for item in chapter_cards})
    event_by_id = {event.event_id: event for event in events}

    for scene in scenes:
        for event_id in scene.event_ids:
            event = event_by_id[event_id]
            target_kind, target_scene_id = targets[event_id]
            if event.scene_id != scene.scene_id or target_scene_id != scene.scene_id:
                raise ValueError("event and target scene ownership must match the containing scene")
            if event.kind.value != target_kind:
                raise ValueError("event kind must match its referenced target type")

    line_by_id = {item.line.line_id: item for item in parsed_lines}
    for scene in scenes:
        line_events = tuple(event_id for event_id in scene.event_ids if targets[event_id][0] == "line")
        if line_events != scene.line_ids:
            raise ValueError("line event order must exactly match scene line order")
        for expected_index, line_id in enumerate(scene.line_ids, start=1):
            if line_by_id[line_id].line_index != expected_index:
                raise ValueError("line indices must match per-scene line order")

        event_positions = {event_id: index for index, event_id in enumerate(scene.event_ids)}
        for beat in (item for item in beats if item.scene_id == scene.scene_id):
            beat_position = event_positions[beat.beat_id]
            if beat.after_line_id is None:
                first_line_position = event_positions[scene.line_ids[0]] if scene.line_ids else len(scene.event_ids)
                if beat_position >= first_line_position:
                    raise ValueError("unanchored beat must precede the first line")
                continue
            anchor_index = scene.line_ids.index(beat.after_line_id)
            next_line_position = (
                event_positions[scene.line_ids[anchor_index + 1]]
                if anchor_index + 1 < len(scene.line_ids)
                else len(scene.event_ids)
            )
            if not (event_positions[beat.after_line_id] < beat_position < next_line_position):
                raise ValueError("beat event must follow its declared line anchor")

    line_scene_by_id = {line_id: item.scene_id for line_id, item in line_by_id.items()}
    for beat in beats:
        if beat.after_line_id is not None and line_scene_by_id.get(beat.after_line_id) != beat.scene_id:
            raise ValueError("beat after_line_id must reference a line in the same scene")
