"""Contract tests for deterministic, pure episode assembly planning."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from kinocut_sound.lines import Emotion, ProfileRef, Prosody
from kinocut_sound.timeline import CueKind


def _apis():
    parser = importlib.import_module("kinocut_sound.script_parser")
    try:
        assembly = importlib.import_module("kinocut_sound.episode_assembly")
    except ModuleNotFoundError:
        pytest.fail("deterministic episode assembly is not implemented")
    return parser, assembly


def _parsed(parser):
    actor = parser.ActorRoute(
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
    document = {
        "episode_id": "episode_001",
        "scenes": [
            {
                "scene_id": "scene_001",
                "pause_after_seconds": 0.5,
                "lines": [
                    {
                        "actor_id": "actor_a",
                        "text": "First line",
                        "kind": "dialogue",
                        "pause_after_seconds": 0.25,
                    },
                    {
                        "actor_id": "actor_a",
                        "text": "Second line",
                        "kind": "off_screen",
                        "pause_after_seconds": 0.0,
                    },
                ],
            }
        ],
    }
    return parser.parse_episode_script(
        document, project_id="project_alpha", created_by="agent:worker_1", actors=(actor,)
    )


def _clip(assembly, line_id: str, marker: str, duration: float):
    return assembly.ClipRef(
        line_id=line_id,
        artifact_hash="sha256:" + marker * 64,
        source_ref=f"clips/{line_id}.wav",
        duration_seconds=duration,
    )


def _foley(assembly):
    return assembly.FoleyCueIntent(
        cue_id="foley_door_close",
        after_line_id="line_0001_0001",
        asset_ref="foley/door_close.wav",
        asset_hash="sha256:" + "c" * 64,
        duration_seconds=0.4,
    )


def _silence(assembly):
    return assembly.DesignedSilenceIntent(
        cue_id="silence_held_breath",
        after_line_id="line_0001_0001",
        quality=assembly.SilenceQuality.HELD_BREATH,
        duration_seconds=0.3,
    )


def test_planner_spots_cues_and_materializes_line_scene_and_designed_pacing():
    parser, assembly = _apis()
    parsed = _parsed(parser)
    clips = (
        _clip(assembly, "line_0001_0002", "b", 2.0),
        _clip(assembly, "line_0001_0001", "a", 1.0),
    )

    plan = assembly.plan_episode_assembly(
        parsed,
        clips=clips,
        foley_cues=(_foley(assembly),),
        designed_silences=(_silence(assembly),),
        created_by="agent:worker_1",
        cancellation_requested=False,
    )

    assert tuple(cue.kind for cue in plan.timeline.cues) == (
        CueKind.LINE,
        CueKind.SILENCE,
        CueKind.SILENCE,
        CueKind.FOLEY,
        CueKind.LINE,
        CueKind.SILENCE,
    )
    assert tuple(cue.source_ref for cue in plan.timeline.cues) == (
        "clips/line_0001_0001.wav",
        "silence/line_pause.json",
        "silence/held_breath.json",
        "foley/door_close.wav",
        "clips/line_0001_0002.wav",
        "silence/scene_pause.json",
    )
    assert plan.timeline.authoritative_duration_seconds == 4.45
    assert plan.line_cue_order == parsed.cue_order


def test_planner_preserves_explicit_profile_and_spatial_routing_intent():
    parser, assembly = _apis()
    parsed = _parsed(parser)
    clips = (
        _clip(assembly, "line_0001_0001", "a", 1.0),
        _clip(assembly, "line_0001_0002", "b", 2.0),
    )

    plan = assembly.plan_episode_assembly(
        parsed,
        clips=clips,
        foley_cues=(),
        designed_silences=(),
        created_by="agent:worker_1",
        cancellation_requested=False,
    )

    assert tuple(route.profile.profile_id for route in plan.routes) == ("voice_a", "voice_a")
    assert tuple(route.spatial_preset for route in plan.routes) == (
        "medium_room",
        "off_screen_distance",
    )
    assert tuple(route.line_id for route in plan.routes) == (
        "line_0001_0001",
        "line_0001_0002",
    )


def test_planner_is_canonical_regardless_of_fake_input_argument_order():
    parser, assembly = _apis()
    parsed = _parsed(parser)
    first_clip = _clip(assembly, "line_0001_0001", "a", 1.0)
    second_clip = _clip(assembly, "line_0001_0002", "b", 2.0)
    first = assembly.plan_episode_assembly(
        parsed,
        clips=(first_clip, second_clip),
        foley_cues=(_foley(assembly),),
        designed_silences=(_silence(assembly),),
        created_by="agent:worker_1",
        cancellation_requested=False,
    )
    second = assembly.plan_episode_assembly(
        parsed,
        clips=(second_clip, first_clip),
        foley_cues=tuple(reversed((_foley(assembly),))),
        designed_silences=tuple(reversed((_silence(assembly),))),
        created_by="agent:worker_1",
        cancellation_requested=False,
    )

    assert first.canonical_id() == second.canonical_id()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    serialized = first.model_dump_json()
    assert "First line" not in serialized
    assert "/home/" not in serialized


@pytest.mark.parametrize(
    "clip_ids",
    [
        ("line_0001_0001",),
        ("line_0001_0001", "extra_line"),
    ],
)
def test_planner_rejects_missing_or_extra_clips_with_safe_custom_error(clip_ids):
    parser, assembly = _apis()
    parsed = _parsed(parser)
    clips = tuple(_clip(assembly, line_id, "a", 1.0) for line_id in clip_ids)

    with pytest.raises(assembly.AssemblyPlanningError) as exc_info:
        assembly.plan_episode_assembly(
            parsed,
            clips=clips,
            foley_cues=(),
            designed_silences=(),
            created_by="agent:worker_1",
            cancellation_requested=False,
        )

    payload = exc_info.value.to_dict()
    assert payload["code"] == "clip_set_mismatch"
    assert payload["suggested_action"] == {"auto_fix": False}
    assert len(payload["message"]) <= 160


def test_planner_rejects_duplicate_or_dangling_cue_contracts():
    parser, assembly = _apis()
    parsed = _parsed(parser)
    clips = (
        _clip(assembly, "line_0001_0001", "a", 1.0),
        _clip(assembly, "line_0001_0002", "b", 2.0),
    )
    duplicate = _foley(assembly)
    with pytest.raises(assembly.AssemblyPlanningError) as exc_info:
        assembly.plan_episode_assembly(
            parsed,
            clips=clips,
            foley_cues=(duplicate, duplicate),
            designed_silences=(),
            created_by="agent:worker_1",
            cancellation_requested=False,
        )
    assert exc_info.value.code == "invalid_cue_contract"

    dangling = assembly.DesignedSilenceIntent(
        cue_id="silence_missing_line",
        after_line_id="line_missing",
        quality=assembly.SilenceQuality.DEAD,
        duration_seconds=0.2,
    )
    with pytest.raises(assembly.AssemblyPlanningError) as exc_info:
        assembly.plan_episode_assembly(
            parsed,
            clips=clips,
            foley_cues=(),
            designed_silences=(dangling,),
            created_by="agent:worker_1",
            cancellation_requested=False,
        )
    assert exc_info.value.code == "invalid_cue_contract"


def test_planner_rejects_absolute_asset_sources_and_cancels_before_validation():
    parser, assembly = _apis()
    parsed = _parsed(parser)
    with pytest.raises(ValidationError):
        assembly.FoleyCueIntent(
            cue_id="foley_leaky",
            after_line_id="line_0001_0001",
            asset_ref="/opt/fixture/door.wav",
            asset_hash="sha256:" + "c" * 64,
            duration_seconds=0.4,
        )

    with pytest.raises(ValidationError):
        assembly.ClipRef(
            line_id="line_0001_0001",
            artifact_hash="sha256:" + "a" * 64,
            source_ref="clips/line.wav",
            duration_seconds="1.0",
        )

    with pytest.raises(assembly.AssemblyPlanningError) as exc_info:
        assembly.plan_episode_assembly(
            parsed,
            clips=(),
            foley_cues=(),
            designed_silences=(),
            created_by="agent:worker_1",
            cancellation_requested=True,
        )
    assert exc_info.value.code == "assembly_cancelled"

    with pytest.raises(assembly.AssemblyPlanningError) as exc_info:
        assembly.plan_episode_assembly(
            parsed,
            clips=(),
            foley_cues=(),
            designed_silences=(),
            created_by="agent:worker_1",
            cancellation_requested="false",
        )
    assert exc_info.value.code == "invalid_assembly"
