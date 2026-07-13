"""Contract tests for standalone, privacy-safe sound script parsing."""

from __future__ import annotations

import importlib

import pytest

from kinocut_sound.lines import Emotion, ProfileRef, Prosody


def _parser_api():
    try:
        return importlib.import_module("kinocut_sound.script_parser")
    except ModuleNotFoundError:
        pytest.fail("standalone script parser is not implemented")


def _actor(api, actor_id: str, profile_id: str):
    return api.ActorRoute(
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


def _document():
    return {
        "episode_id": "episode_001",
        "scenes": [
            {
                "scene_id": "scene_001",
                "pause_after_seconds": 0.5,
                "lines": [
                    {
                        "actor_id": "actor_a",
                        "text": "Keep this private.",
                        "kind": "dialogue",
                        "pause_after_seconds": 0.25,
                    },
                    {
                        "actor_id": "actor_b",
                        "text": "This is the confessional.",
                        "kind": "confessional",
                        "pause_after_seconds": 0.0,
                    },
                ],
            },
            {
                "scene_id": "scene_002",
                "pause_after_seconds": 0.0,
                "lines": [
                    {
                        "actor_id": "actor_a",
                        "text": "From down the hall.",
                        "kind": "off_screen",
                        "pause_after_seconds": 0.0,
                    }
                ],
            },
        ],
    }


def test_parser_emits_typed_hashed_lines_in_source_order_without_raw_text():
    api = _parser_api()
    actors = (_actor(api, "actor_a", "voice_a"), _actor(api, "actor_b", "voice_b"))

    parsed = api.parse_episode_script(
        _document(), project_id="project_alpha", created_by="agent:worker_1", actors=actors
    )

    assert parsed.cue_order == ("cue_0001_0001", "cue_0001_0002", "cue_0002_0001")
    assert tuple(item.line.profile.profile_id for item in parsed.parsed_lines) == (
        "voice_a",
        "voice_b",
        "voice_a",
    )
    assert tuple(item.line.spatial_preset for item in parsed.parsed_lines) == (
        "medium_room",
        "close_mic_dry",
        "off_screen_distance",
    )
    serialized = parsed.model_dump_json()
    assert "Keep this private" not in serialized
    assert "This is the confessional" not in serialized
    assert "/home/" not in serialized
    assert all(item.line.text_hash.startswith("sha256:") for item in parsed.parsed_lines)


def test_parser_is_canonical_and_deterministic_for_identical_semantic_input():
    api = _parser_api()
    actors = (_actor(api, "actor_a", "voice_a"), _actor(api, "actor_b", "voice_b"))

    first = api.parse_episode_script(
        _document(), project_id="project_alpha", created_by="agent:worker_1", actors=actors
    )
    second = api.parse_episode_script(
        _document(), project_id="project_alpha", created_by="agent:worker_1", actors=actors
    )

    assert first.canonical_id() == second.canonical_id()
    assert first.source_hash == second.source_hash
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda doc: doc["scenes"][0]["lines"][0].update(actor_id="actor_unknown"), "unknown_actor"),
        (lambda doc: doc["scenes"][1].update(scene_id="scene_001"), "invalid_scene"),
        (lambda doc: doc["scenes"][0]["lines"][0].update(text="   "), "invalid_line"),
        (lambda doc: doc["scenes"][0]["lines"][0].update(pause_after_seconds="0.25"), "invalid_line"),
        (lambda doc: doc.update(unexpected_field="do not serialize this"), "invalid_script"),
    ],
)
def test_parser_rejects_actor_line_scene_and_shape_errors_with_bounded_safe_errors(mutate, code):
    api = _parser_api()
    actors = (_actor(api, "actor_a", "voice_a"), _actor(api, "actor_b", "voice_b"))
    document = _document()
    mutate(document)

    with pytest.raises(api.ScriptParseError) as exc_info:
        api.parse_episode_script(
            document, project_id="project_alpha", created_by="agent:worker_1", actors=actors
        )

    payload = exc_info.value.to_dict()
    assert payload["code"] == code
    assert payload["suggested_action"] == {"auto_fix": False}
    assert len(payload["message"]) <= 160
    assert "do not serialize this" not in payload["message"]


def test_parser_rejects_duplicate_actor_routes_before_reading_lines():
    api = _parser_api()
    actors = (_actor(api, "actor_a", "voice_a"), _actor(api, "actor_a", "voice_b"))

    with pytest.raises(api.ScriptParseError) as exc_info:
        api.parse_episode_script(
            _document(), project_id="project_alpha", created_by="agent:worker_1", actors=actors
        )

    assert exc_info.value.code == "invalid_actor_roster"
