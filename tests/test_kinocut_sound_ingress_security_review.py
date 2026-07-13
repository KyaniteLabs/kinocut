"""Hostile public-ingress regressions for S4 caller-owned iterables."""

from __future__ import annotations

from collections.abc import Mapping
import traceback

import pytest

from kinocut_sound import episode_assembly as assembly
from kinocut_sound import script_parser as parser
from kinocut_sound.lines import Emotion, ProfileRef, Prosody
from kinocut_sound.limits import MAX_SCRIPT_ACTORS


def _actor() -> parser.ActorRoute:
    return parser.ActorRoute(
        actor_id="actor_a",
        profile=ProfileRef(profile_id="voice_a", version=1),
        dialogue_spatial_preset="medium_room",
        confessional_spatial_preset="close_mic_dry",
        off_screen_spatial_preset="off_screen_distance",
        narration_spatial_preset="medium_room",
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        inherit_loudness=True,
    )


def _parsed() -> parser.ParsedScript:
    return parser.parse_episode_script(
        {
            "episode_id": "ingress_review",
            "scenes": [
                {
                    "scene_id": "scene_review",
                    "pause_after_seconds": 0.0,
                    "lines": [
                        {
                            "actor_id": "actor_a",
                            "text": "First.",
                            "kind": "dialogue",
                            "pause_after_seconds": 0.0,
                        },
                        {
                            "actor_id": "actor_a",
                            "text": "Second.",
                            "kind": "dialogue",
                            "pause_after_seconds": 0.0,
                        },
                    ],
                }
            ],
        },
        project_id="project_alpha",
        created_by="agent:worker_1",
        actors=(_actor(),),
    )


def _assert_safe_error(error, marker):
    assert marker not in str(error)
    assert marker not in str(error.__cause__)
    assert marker not in str(error.__context__)
    assert marker not in "".join(traceback.format_exception(error))


class _ExplodingDocument(Mapping):
    marker = "HOSTILE_DOCUMENT_TRAVERSAL"

    def __len__(self):
        return 1

    def __iter__(self):
        return iter(("scenes",))

    def __getitem__(self, key):
        raise RuntimeError(self.marker)

    def get(self, key, default=None):
        raise RuntimeError(self.marker)


@pytest.mark.parametrize("wf", [False, True])
def test_parser_normalizes_document_traversal_exceptions(wf):
    document = _ExplodingDocument()

    with pytest.raises(parser.ScriptParseError) as caught:
        if wf:
            parser.parse_wf_episode_script(
                document,
                project_id="project_alpha",
                created_by="agent:worker_1",
                actors=(),
                character_routes={},
                narrator_character="Narrator",
            )
        else:
            parser.parse_episode_script(
                document,
                project_id="project_alpha",
                created_by="agent:worker_1",
                actors=(),
            )

    _assert_safe_error(caught.value, document.marker)


class _ExplodingRoutes(Mapping):
    marker = "HOSTILE_ROUTE_TRAVERSAL"

    def __len__(self):
        return 1

    def __iter__(self):
        return iter(("Alice",))

    def __getitem__(self, key):
        return "actor_a"

    def items(self):
        raise RuntimeError(self.marker)


def test_wf_parser_normalizes_route_traversal_exceptions():
    routes = _ExplodingRoutes()

    with pytest.raises(parser.ScriptParseError) as caught:
        parser.parse_wf_episode_script(
            {"episode_id": "wf_routes", "scenes": []},
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(_actor(),),
            character_routes=routes,
            narrator_character="Narrator",
        )

    _assert_safe_error(caught.value, routes.marker)


def test_assembly_normalizes_generator_traversal_exceptions():
    marker = "HOSTILE_CLIP_GENERATOR"
    parsed = _parsed()
    first = parsed.parsed_lines[0]
    clip = assembly.ClipRef(
        line_id=first.line.line_id,
        artifact_hash="sha256:" + "a" * 64,
        source_ref="clips/first.wav",
        duration_seconds=1.0,
    )

    def clips():
        yield clip
        raise RuntimeError(marker)

    with pytest.raises(assembly.AssemblyPlanningError) as caught:
        assembly.plan_episode_assembly(
            parsed,
            clips=clips(),
            created_by="agent:worker_1",
            cancellation_requested=False,
        )

    _assert_safe_error(caught.value, marker)


class _DishonestRoutes(Mapping):
    def __init__(self):
        self.consumed = 0

    def __len__(self):
        return 1

    def __iter__(self):
        return (f"Character {index}" for index in range(5_001))

    def __getitem__(self, key):
        return "actor_a"

    def items(self):
        for index in range(5_001):
            self.consumed += 1
            yield f"Character {index}", "actor_a"


def test_wf_route_ceiling_counts_actual_entries_not_reported_length():
    routes = _DishonestRoutes()

    with pytest.raises(parser.ScriptParseError) as caught:
        parser.parse_wf_episode_script(
            {"episode_id": "wf_routes", "scenes": []},
            project_id="project_alpha",
            created_by="agent:worker_1",
            actors=(_actor(),),
            character_routes=routes,
            narrator_character="Narrator",
        )

    assert caught.value.code == "invalid_actor_roster"
    assert routes.consumed == MAX_SCRIPT_ACTORS + 1
