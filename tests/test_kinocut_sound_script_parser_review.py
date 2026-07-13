"""Hostile review regressions for S4 script parsing contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.lines import Emotion, ProfileRef, Prosody
from kinocut_sound import episode_assembly as assembly
from kinocut_sound.limits import (
    MAX_SCRIPT_ACTORS,
    MAX_SCRIPT_BEATS_PER_SCENE,
    MAX_SCRIPT_EVENTS_PER_SCENE,
    MAX_SCRIPT_LINES_PER_SCENE,
    MAX_SCRIPT_SCENES,
    MAX_SCRIPT_TEXT_LENGTH_CHARS,
    MAX_SCRIPT_TURNS_PER_SCENE,
)

from kinocut_sound import script_parser as parser


def _actor(actor_id: str, profile_id: str) -> parser.ActorRoute:
    return parser.ActorRoute(
        actor_id=actor_id,
        profile=ProfileRef(profile_id=profile_id, version=1),
        dialogue_spatial_preset="medium_room",
        confessional_spatial_preset="close_mic_dry",
        off_screen_spatial_preset="off_screen_distance",
        narration_spatial_preset="medium_room",
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        inherit_loudness=True,
    )


def _generic_document():
    return {
        "episode_id": "episode_review",
        "scenes": [
            {
                "scene_id": "scene_review",
                "pause_after_seconds": 0.0,
                "lines": [
                    {
                        "actor_id": "narrator",
                        "text": "A door opens in the dark.",
                        "kind": "action",
                        "pause_after_seconds": 0.0,
                    },
                    {
                        "actor_id": "actor_a",
                        "text": "I remember this place.",
                        "kind": "voiceover",
                        "pause_after_seconds": 0.0,
                    },
                ],
                "beats": [
                    {
                        "kind": "foley",
                        "text": "Door latch",
                        "after_line_index": 1,
                        "duration_seconds": 0.4,
                        "asset_ref": "foley/door_latch.wav",
                        "asset_hash": "sha256:" + "a" * 64,
                    },
                    {
                        "kind": "designed_silence",
                        "text": "Held breath",
                        "after_line_index": 1,
                        "duration_seconds": 0.3,
                        "silence_quality": "held_breath",
                    },
                    {
                        "kind": "pace",
                        "text": "Memory settles",
                        "after_line_index": 2,
                        "duration_seconds": 0.2,
                    },
                ],
            }
        ],
    }


def _generic_parsed() -> parser.ParsedScript:
    return parser.parse_episode_script(
        _generic_document(),
        project_id="project_alpha",
        created_by="agent:worker_1",
        actors=(
            _actor("narrator", "voice_narrator"),
            _actor("actor_a", "voice_a"),
        ),
    )


def _two_scene_parsed() -> parser.ParsedScript:
    document = _generic_document()
    first_scene = document["scenes"][0]
    first_scene["lines"] = first_scene["lines"][:1]
    first_scene["beats"] = first_scene["beats"][:1]
    document["scenes"].append(
        {
            "scene_id": "scene_other",
            "pause_after_seconds": 0.0,
            "lines": [
                {
                    "actor_id": "actor_a",
                    "text": "Across the hall.",
                    "kind": "dialogue",
                    "pause_after_seconds": 0.0,
                }
            ],
        }
    )
    return parser.parse_episode_script(
        document,
        project_id="project_alpha",
        created_by="agent:worker_1",
        actors=(
            _actor("narrator", "voice_narrator"),
            _actor("actor_a", "voice_a"),
        ),
    )


def _chapter_only_parsed() -> parser.ParsedScript:
    return parser.parse_wf_episode_script(
        {
            "episode_id": "wf_chapter_review",
            "scenes": [
                {
                    "scene_id": "wf_scene",
                    "turns": [
                        {
                            "character": "Narrator",
                            "text": "Chapter One",
                            "confessional": False,
                        }
                    ],
                }
            ],
        },
        project_id="project_alpha",
        created_by="agent:worker_1",
        actors=(),
        character_routes={},
        narrator_character="Narrator",
    )


def _generic_with_chapter_payload():
    payload = _generic_parsed().model_dump(mode="json")
    chapter = _chapter_only_parsed().model_dump(mode="json")["chapter_cards"][0]
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


def test_generic_parser_represents_action_narration_voiceover_and_beats_in_source_order():
    parsed = _generic_parsed()

    assert tuple(item.performance_kind.value for item in parsed.parsed_lines) == (
        "action",
        "voiceover",
    )
    assert tuple(beat.kind.value for beat in parsed.beats) == (
        "foley",
        "designed_silence",
        "pace",
    )
    assert parsed.scenes[0].event_ids == (
        "line_0001_0001",
        "beat_0001_0001",
        "beat_0001_0002",
        "line_0001_0002",
        "beat_0001_0003",
    )
    assert tuple(item.line.spatial_preset for item in parsed.parsed_lines) == (
        "medium_room",
        "medium_room",
    )
    serialized = parsed.model_dump_json()
    assert "A door opens in the dark" not in serialized
    assert "Door latch" not in serialized
    assert "/home/" not in serialized


def test_wf_parser_maps_turns_and_keeps_narrator_as_hashed_chapter_card_only():
    document = {
        "episode_id": "wf_episode",
        "scenes": [
            {
                "scene_id": "wf_scene",
                "turns": [
                    {"character": "Narrator", "text": "Chapter One", "confessional": False},
                    {"character": "Alice", "text": "Hello.", "confessional": False},
                    {"character": "Bob", "text": "Privately.", "confessional": True},
                ],
            }
        ],
    }

    parsed = parser.parse_wf_episode_script(
        document,
        project_id="project_alpha",
        created_by="agent:worker_1",
        actors=(_actor("alice", "voice_alice"), _actor("bob", "voice_bob")),
        character_routes={"Alice": "alice", "Bob": "bob"},
        narrator_character="Narrator",
    )

    assert tuple(item.line.character_id for item in parsed.parsed_lines) == ("alice", "bob")
    assert tuple(item.performance_kind.value for item in parsed.parsed_lines) == (
        "dialogue",
        "confessional",
    )
    assert len(parsed.chapter_cards) == 1
    assert parsed.chapter_cards[0].text_hash.startswith("sha256:")
    assert parsed.scenes[0].event_ids == (
        "chapter_0001_0001",
        "line_0001_0001",
        "line_0001_0002",
    )
    serialized = parsed.model_dump_json()
    assert "Chapter One" not in serialized
    assert "Privately" not in serialized
    assert "Narrator" not in tuple(item.line.character_id for item in parsed.parsed_lines)


@pytest.mark.parametrize("defect", ["duplicate_line", "missing_membership", "reordered_membership"])
def test_parsed_script_model_rejects_referential_integrity_defects(defect):
    payload = _generic_parsed().model_dump(mode="json")
    if defect == "duplicate_line":
        payload["parsed_lines"][1]["line"]["line_id"] = payload["parsed_lines"][0]["line"]["line_id"]
    elif defect == "missing_membership":
        payload["scenes"][0]["line_ids"] = payload["scenes"][0]["line_ids"][:1]
    else:
        payload["scenes"][0]["line_ids"] = list(reversed(payload["scenes"][0]["line_ids"]))

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("defect", ["event_scene", "beat_scene"])
def test_parsed_script_rejects_event_or_beat_scene_ownership_mismatch(defect):
    payload = _generic_parsed().model_dump(mode="json")
    if defect == "event_scene":
        payload["events"][0]["scene_id"] = "scene_other"
    else:
        payload["beats"][0]["scene_id"] = "scene_other"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize(("event_index", "wrong_kind"), [(0, "beat"), (1, "line")])
def test_parsed_script_rejects_line_or_beat_event_kind_mismatch(event_index, wrong_kind):
    payload = _generic_parsed().model_dump(mode="json")
    payload["events"][event_index]["kind"] = wrong_kind

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_chapter_event_kind_mismatch():
    payload = _chapter_only_parsed().model_dump(mode="json")
    payload["events"][0]["kind"] = "line"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_beat_after_line_from_another_scene():
    payload = _two_scene_parsed().model_dump(mode="json")
    payload["beats"][0]["after_line_id"] = "line_0002_0001"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


def test_parsed_script_rejects_chapter_card_scene_ownership_mismatch():
    payload = _chapter_only_parsed().model_dump(mode="json")
    payload["chapter_cards"][0]["scene_id"] = "scene_other"

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("target_type", ["beat", "chapter_card"])
def test_parsed_script_rejects_same_type_target_id_duplicates(target_type):
    if target_type == "beat":
        payload = _generic_parsed().model_dump(mode="json")
        retired_id = payload["beats"][1]["beat_id"]
        payload["beats"][1]["beat_id"] = payload["beats"][0]["beat_id"]
        _remove_event(payload, retired_id)
    else:
        payload = _generic_with_chapter_payload()
        payload["chapter_cards"].append(payload["chapter_cards"][0].copy())

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)


@pytest.mark.parametrize("collision", ["line_beat", "line_chapter", "beat_chapter"])
def test_parsed_script_rejects_cross_type_target_id_collisions(collision):
    payload = _generic_with_chapter_payload()
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


def test_parser_revalidates_poisoned_actor_profiles_at_public_boundary():
    poisoned_profile = ProfileRef.model_construct(
        profile_id="RAW PROFILE SECRET",
        version=1,
    )
    actor = _actor("actor_a", "voice_a").model_copy(update={"profile": poisoned_profile})

    with pytest.raises(parser.ScriptParseError):
        parser.parse_episode_script(
            _generic_document(),
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(_actor("narrator", "voice_narrator"), actor),
        )


def test_parser_translates_wrong_actor_runtime_type_to_custom_error():
    with pytest.raises(parser.ScriptParseError):
        parser.parse_episode_script(
            _generic_document(),
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(object(),),
        )


def test_wf_parser_translates_wrong_narrator_runtime_type_to_custom_error():
    document = {
        "episode_id": "wf_runtime_type",
        "scenes": [
            {
                "scene_id": "wf_scene",
                "turns": [
                    {
                        "character": "Narrator",
                        "text": "Chapter One",
                        "confessional": False,
                    }
                ],
            }
        ],
    }

    with pytest.raises(parser.ScriptParseError):
        parser.parse_wf_episode_script(
            document,
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(),
            character_routes={},
            narrator_character=object(),
        )


@pytest.mark.parametrize("defect", ["line_event_order", "line_index", "beat_anchor"])
def test_parsed_script_rejects_source_event_order_contradictions(defect):
    payload = _generic_parsed().model_dump(mode="json")
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


def _limit_line(text="Line"):
    return {
        "actor_id": "actor_0000",
        "text": text,
        "kind": "dialogue",
        "pause_after_seconds": 0.0,
    }


def _limit_beat():
    return {
        "kind": "pace",
        "text": "Beat",
        "after_line_index": 1,
        "duration_seconds": 0.1,
    }


@pytest.mark.parametrize(
    "ceiling",
    ["actor", "scene", "line", "beat", "turn", "event", "text"],
)
def test_every_exported_script_resource_ceiling_rejects_with_custom_error(ceiling):
    actor = _actor("actor_0000", "voice_a")
    actors = (actor,)
    document = {
        "episode_id": "episode_limits",
        "scenes": [
            {
                "scene_id": "scene_0000",
                "pause_after_seconds": 0.0,
                "lines": [_limit_line()],
            }
        ],
    }
    if ceiling == "actor":
        actors = tuple(_actor(f"actor_{index:04d}", "voice_a") for index in range(MAX_SCRIPT_ACTORS + 1))
    elif ceiling == "scene":
        document["scenes"] = [
            {
                "scene_id": f"scene_{index:04d}",
                "pause_after_seconds": 0.0,
                "lines": [_limit_line()],
            }
            for index in range(MAX_SCRIPT_SCENES + 1)
        ]
    elif ceiling == "line":
        document["scenes"][0]["lines"] = [_limit_line() for _ in range(MAX_SCRIPT_LINES_PER_SCENE + 1)]
    elif ceiling == "beat":
        document["scenes"][0]["beats"] = [_limit_beat() for _ in range(MAX_SCRIPT_BEATS_PER_SCENE + 1)]
    elif ceiling == "event":
        document["scenes"][0]["lines"] = [_limit_line() for _ in range(MAX_SCRIPT_LINES_PER_SCENE)]
        beat_count = MAX_SCRIPT_EVENTS_PER_SCENE - MAX_SCRIPT_LINES_PER_SCENE + 1
        document["scenes"][0]["beats"] = [_limit_beat() for _ in range(beat_count)]
    elif ceiling == "text":
        document["scenes"][0]["lines"][0]["text"] = "x" * (MAX_SCRIPT_TEXT_LENGTH_CHARS + 1)
    else:
        wf_document = {
            "episode_id": "wf_limits",
            "scenes": [
                {
                    "scene_id": "wf_scene",
                    "turns": [
                        {
                            "character": "Narrator",
                            "text": "Chapter",
                            "confessional": False,
                        }
                        for _ in range(MAX_SCRIPT_TURNS_PER_SCENE + 1)
                    ],
                }
            ],
        }
        with pytest.raises(parser.ScriptParseError):
            parser.parse_wf_episode_script(
                wf_document,
                project_id="project_alpha",
                created_by="agent:worker_1",
                actors=(),
                character_routes={},
                narrator_character="Narrator",
            )
        return

    with pytest.raises(parser.ScriptParseError):
        parser.parse_episode_script(
            document,
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=actors,
        )


@pytest.mark.parametrize(
    "character_routes",
    [object(), {1: "actor_a"}, {"Alice": 1}],
)
def test_wf_character_routes_runtime_types_are_bounded_custom_errors(character_routes):
    document = {
        "episode_id": "wf_routes",
        "scenes": [
            {
                "scene_id": "wf_scene",
                "turns": [{"character": "Alice", "text": "Hello.", "confessional": False}],
            }
        ],
    }

    with pytest.raises(parser.ScriptParseError):
        parser.parse_wf_episode_script(
            document,
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(_actor("actor_a", "voice_a"),),
            character_routes=character_routes,
            narrator_character="Narrator",
        )


def _rename_beat_id(payload, new_id):
    old_id = payload["beats"][0]["beat_id"]
    payload["beats"][0]["beat_id"] = new_id
    next(item for item in payload["events"] if item["event_id"] == old_id)["event_id"] = new_id
    scene_event_ids = payload["scenes"][0]["event_ids"]
    scene_event_ids[scene_event_ids.index(old_id)] = new_id


@pytest.mark.parametrize("collision", ["line_cue_beat", "line_pause_beat", "scene_pause_beat"])
def test_parsed_script_rejects_every_timeline_emitting_id_collision(collision):
    payload = _generic_parsed().model_dump(mode="json")
    if collision == "line_cue_beat":
        beat_id = payload["beats"][0]["beat_id"]
        payload["parsed_lines"][0]["cue_id"] = beat_id
        payload["cue_order"][0] = beat_id
    elif collision == "line_pause_beat":
        payload["parsed_lines"][0]["pause_after_seconds"] = 0.5
        line_id = payload["parsed_lines"][0]["line"]["line_id"]
        _rename_beat_id(payload, assembly._bounded_pause_cue_id("line", line_id))
    else:
        payload["scenes"][0]["pause_after_seconds"] = 0.5
        scene_id = payload["scenes"][0]["scene_id"]
        _rename_beat_id(payload, assembly._bounded_pause_cue_id("scene", scene_id))

    with pytest.raises(ValidationError):
        parser.ParsedScript.model_validate(payload)
