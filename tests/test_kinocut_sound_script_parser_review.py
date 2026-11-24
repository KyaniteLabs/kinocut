"""Integrity contracts for typed sound script records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinocut_sound import script_parser as parser
from kinocut_sound._timeline_identity import bounded_pause_cue_id


@pytest.fixture
def script_payloads():
    fixture = Path(__file__).with_name("fixtures") / "sound_script_records.json"
    payloads = json.loads(fixture.read_text(encoding="utf-8"))
    for payload in payloads.values():
        parser.ParsedScript.model_validate(payload)
    return payloads


def _generic_with_chapter_payload(script_payloads):
    payload = script_payloads["generic"]
    chapter = script_payloads["chapter_only"]["chapter_cards"][0]
    chapter["chapter_id"] = "chapter_review"
    chapter["scene_id"] = "scene_review"
    payload["chapter_cards"].append(chapter)
    payload["events"].append(
        {
            "event_id": "chapter_review",
            "scene_id": "scene_review",
            "kind": "chapter_card",
        }
    )
    payload["scenes"][0]["event_ids"].append("chapter_review")
    return payload


def _remove_event(payload, event_id):
    payload["events"] = [event for event in payload["events"] if event["event_id"] != event_id]
    payload["scenes"][0]["event_ids"] = [item for item in payload["scenes"][0]["event_ids"] if item != event_id]


@pytest.mark.parametrize("defect", ["duplicate_line", "missing_membership", "reordered_membership"])
def test_parsed_script_model_rejects_referential_integrity_defects(defect, script_payloads):
    payload = script_payloads["generic"]
    if defect == "duplicate_line":
        payload["parsed_lines"][1]["line"]["line_id"] = payload["parsed_lines"][0]["line"]["line_id"]
    elif defect == "missing_membership":
        payload["scenes"][0]["line_ids"] = payload["scenes"][0]["line_ids"][:1]
    else:
        payload["scenes"][0]["line_ids"] = list(reversed(payload["scenes"][0]["line_ids"]))

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("defect", ["event_scene", "beat_scene"])
def test_parsed_script_rejects_event_or_beat_scene_ownership_mismatch(defect, script_payloads):
    payload = script_payloads["generic"]
    if defect == "event_scene":
        payload["events"][0]["scene_id"] = "scene_other"
    else:
        payload["beats"][0]["scene_id"] = "scene_other"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize(("event_index", "wrong_kind"), [(0, "beat"), (1, "line")])
def test_parsed_script_rejects_line_or_beat_event_kind_mismatch(event_index, wrong_kind, script_payloads):
    payload = script_payloads["generic"]
    payload["events"][event_index]["kind"] = wrong_kind

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_chapter_event_kind_mismatch(script_payloads):
    payload = script_payloads["chapter_only"]
    payload["events"][0]["kind"] = "line"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_beat_after_line_from_another_scene(script_payloads):
    payload = script_payloads["two_scene"]
    payload["beats"][0]["after_line_id"] = "line_0002_0001"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_chapter_card_scene_ownership_mismatch(script_payloads):
    payload = script_payloads["chapter_only"]
    payload["chapter_cards"][0]["scene_id"] = "scene_other"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("target_type", ["beat", "chapter_card"])
def test_parsed_script_rejects_same_type_target_id_duplicates(target_type, script_payloads):
    if target_type == "beat":
        payload = script_payloads["generic"]
        retired_id = payload["beats"][1]["beat_id"]
        payload["beats"][1]["beat_id"] = payload["beats"][0]["beat_id"]
        _remove_event(payload, retired_id)
    else:
        payload = _generic_with_chapter_payload(script_payloads)
        payload["chapter_cards"].append(payload["chapter_cards"][0].copy())

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("collision", ["line_beat", "line_chapter", "beat_chapter"])
def test_parsed_script_rejects_cross_type_target_id_collisions(collision, script_payloads):
    payload = _generic_with_chapter_payload(script_payloads)
    line_id = payload["parsed_lines"][0]["line"]["line_id"]
    beat_id = payload["beats"][0]["beat_id"]
    chapter_id = payload["chapter_cards"][0]["chapter_id"]

    if collision == "line_beat":
        payload["beats"][0]["beat_id"] = line_id
        _remove_event(payload, beat_id)
        surviving_id, surviving_kind = line_id, "beat"
    elif collision == "line_chapter":
        payload["chapter_cards"][0]["chapter_id"] = line_id
        _remove_event(payload, chapter_id)
        surviving_id, surviving_kind = line_id, "chapter_card"
    else:
        payload["chapter_cards"][0]["chapter_id"] = beat_id
        _remove_event(payload, chapter_id)
        surviving_id, surviving_kind = beat_id, "chapter_card"

    event = next(item for item in payload["events"] if item["event_id"] == surviving_id)
    event["kind"] = surviving_kind

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("defect", ["line_event_order", "line_index", "beat_anchor"])
def test_parsed_script_rejects_source_event_order_contradictions(defect, script_payloads):
    payload = script_payloads["generic"]
    if defect == "line_event_order":
        payload["events"][0], payload["events"][3] = (
            payload["events"][3],
            payload["events"][0],
        )
        payload["scenes"][0]["event_ids"] = [item["event_id"] for item in payload["events"]]
    elif defect == "line_index":
        payload["parsed_lines"][0]["line_index"] = 7
    else:
        beat_event = payload["events"].pop(1)
        payload["events"].insert(0, beat_event)
        payload["scenes"][0]["event_ids"] = [item["event_id"] for item in payload["events"]]

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def _rename_beat_id(payload, new_id):
    old_id = payload["beats"][0]["beat_id"]
    payload["beats"][0]["beat_id"] = new_id
    next(item for item in payload["events"] if item["event_id"] == old_id)["event_id"] = new_id
    scene_event_ids = payload["scenes"][0]["event_ids"]
    scene_event_ids[scene_event_ids.index(old_id)] = new_id


@pytest.mark.parametrize("collision", ["line_cue_beat", "line_pause_beat", "scene_pause_beat"])
def test_parsed_script_rejects_every_timeline_emitting_id_collision(collision, script_payloads):
    payload = script_payloads["generic"]
    if collision == "line_cue_beat":
        beat_id = payload["beats"][0]["beat_id"]
        payload["parsed_lines"][0]["cue_id"] = beat_id
        payload["cue_order"][0] = beat_id
    elif collision == "line_pause_beat":
        payload["parsed_lines"][0]["pause_after_seconds"] = 0.5
        line_id = payload["parsed_lines"][0]["line"]["line_id"]
        _rename_beat_id(payload, bounded_pause_cue_id("line", line_id))
    else:
        payload["scenes"][0]["pause_after_seconds"] = 0.5
        scene_id = payload["scenes"][0]["scene_id"]
        _rename_beat_id(payload, bounded_pause_cue_id("scene", scene_id))

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)
