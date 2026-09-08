"""Valid companion fields for the checked sound numeric-guard matrix."""

from copy import deepcopy
from importlib import import_module

SHA = "sha256:" + "a" * 64
LINE = {
    "line_id": "line",
    "character_id": "actor",
    "profile": {"profile_id": "voice", "version": 1},
    "text_hash": SHA,
    "text_length_chars": 5,
    "prosody": {},
    "emotion": {"label": "neutral", "intensity": 0.5},
    "spatial_preset": "center",
    "inherit_loudness": True,
}
LOUDNESS = {
    "preset": "stream_podcast",
    "integrated_lufs": -14.0,
    "true_peak_dbtp": -1.0,
    "lra_lu": 0.0,
    "within_tolerance": True,
}
SECTION = {"plan_hash": SHA, "loudness": LOUDNESS, "human_review_required": True, "profile_versions": (("voice", 1),)}
CUE = {"cue_id": "cue", "start_seconds": 0.0, "duration_seconds": 1.0, "kind": "line", "source_ref": "audio.wav"}
INPUT_LINE = {"actor_id": "actor", "text": "hello", "kind": "dialogue", "pause_after_seconds": 0.0}
DUCK = {
    "source_bus_id": "dialogue",
    "target_bus_id": "ambience",
    "attenuation_db": 9.0,
    "attack_ms": 80.0,
    "release_ms": 350.0,
    "recovery_ms": 500.0,
}

MODEL_DATA = {
    "kinocut_sound.episode_assembly.ClipRef": {
        "line_id": "line",
        "artifact_hash": SHA,
        "source_ref": "audio.wav",
        "duration_seconds": 1.0,
    },
    "kinocut_sound.episode_assembly.FoleyCueIntent": {
        "cue_id": "foley",
        "after_line_id": "line",
        "asset_ref": "foley",
        "asset_hash": SHA,
        "duration_seconds": 1.0,
    },
    "kinocut_sound.episode_assembly.DesignedSilenceIntent": {
        "cue_id": "silence",
        "after_line_id": "line",
        "quality": "dead",
        "duration_seconds": 1.0,
    },
    "kinocut_sound.script_parser.ParsedLine": {
        "scene_id": "scene",
        "line_index": 1,
        "cue_id": "line",
        "pause_after_seconds": 0.0,
        "performance_kind": "dialogue",
        "line": LINE,
    },
    "kinocut_sound.script_parser.ParsedScene": {
        "scene_id": "scene",
        "line_ids": ("line",),
        "event_ids": ("line",),
        "pause_after_seconds": 0.0,
    },
    "kinocut_sound.script_parser._LineInput": INPUT_LINE,
    "kinocut_sound.script_parser._SceneInput": {
        "scene_id": "scene",
        "pause_after_seconds": 0.0,
        "lines": (INPUT_LINE,),
    },
    "kinocut_sound.receipt.LoudnessVerification": LOUDNESS,
    "kinocut_sound.receipt.SoundReceiptSection": SECTION,
    "kinocut_sound.routing.Track": {
        "track_id": "track",
        "destination_bus_id": "bus",
        "gain_db": 0.0,
        "pan_position": 0.0,
        "pan_law": "linear",
        "muted": False,
        "soloed": False,
    },
    "kinocut_sound.routing.Bus": {"bus_id": "bus", "kind": "dialogue"},
    "kinocut_sound.routing.SendReturn": {
        "send_id": "send",
        "source_bus_id": "dialogue",
        "destination_bus_id": "ambience",
    },
    "kinocut_sound.routing.DuckingSidechain": DUCK,
    "kinocut_sound.routing.AutomationPoint": {"time_seconds": 0.0, "value": 0.0},
    "kinocut_sound.voice.roster.VoiceSlotBase": {
        "pitch_semitones": 0.0,
        "rate": 1.0,
        "volume_db": 0.0,
        "formant_offset": 0.0,
    },
    "kinocut_sound.capability.CostDisclosure": {
        "provider_id": "provider",
        "region": "local",
        "data_classes": ("audio",),
        "retention_ceiling_days": 0,
        "estimated_cost_usd_per_call": 0.25,
        "confirmed": True,
    },
    "kinocut_sound.capability.AdapterDescriptor": {
        "adapter_id": "adapter",
        "kind": "tts",
        "locality": "local",
        "provider_class": "offline",
    },
    "kinocut_sound.delivery.LoudnessTarget": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0},
    "kinocut_sound.delivery.DeliveryPolicy": {},
    "kinocut_sound.lines.Emotion": {"label": "neutral", "intensity": 0.5},
    "kinocut_sound.lines.Line": LINE,
    "kinocut_sound.timeline.Cue": CUE,
    "kinocut_sound.timeline.Timeline": {"cues": (CUE,)},
    "kinocut_sound.world.layers.DuckingContract": DUCK,
    "kinocut_sound.world.layers.AmbientLayer": {
        "layer_id": "hum",
        "asset_ref": "bed",
        "gain_db": -9.0,
        "muted": False,
        "soloed": False,
    },
    "kinocut_sound.world.presets.LocationPreset": {
        "preset_id": "room",
        "bed_asset_refs": ("bed",),
        "base_layer_ids": ("hum",),
        "base_gain_db": -6.0,
    },
    "kinocut_sound.world.presets.DeckTexturePreset": {
        "deck_id": "deck",
        "tonal_layer_refs": ("hum", "air"),
        "character": "bright",
    },
    "kinocut_sound.world.loop.SeamlessLoop": {
        "loop_label": "loop",
        "source_duration_seconds": 120.0,
        "target_duration_seconds": 60.0,
        "crossfade_seconds": 0.5,
    },
    "kinocut_sound.world.d41_port.BedSpec": {
        "bed_id": "bed",
        "kind": "ambient_bed",
        "description_hash": SHA,
        "duration_seconds": 30.0,
    },
    "kinocut_sound.world.catalog.CatalogAsset": {
        "asset_id": "bed",
        "kind": "bed",
        "duration_seconds": 120.0,
        "license_ref": {"license_id": "cc_by_4", "asset_hash": SHA},
        "provenance": {"content_hash": SHA, "source_ref": "beds/room.wav"},
    },
    "kinocut_sound.world.audition.AuditionRequest": {
        "bed_id": "bed",
        "context": {"reviewer_id": "reviewer", "project_id": "project", "episode_id": "episode", "note_hash": SHA},
        "layer_ids": ("hum", "air"),
        "target_duration_seconds": 120.0,
        "reel_label": "review",
    },
    "kinocut_sound.receipt.SoundReceipt": {
        "operation": "mix",
        "output_hash": SHA,
        "sound": SECTION,
        "output_duration": 1.0,
    },
    "kinocut_sound.routing.LatencyCompensation": {"policy": "sample_accurate"},
    "kinocut_sound.receipt.OrderedInput": {
        "asset_id": SHA,
        "input_hash": SHA,
        "role": "dialogue",
        "safe_display_name": "audio.wav",
    },
    "kinocut_sound.receipt.Transformation": {"tool": "ffmpeg", "operation": "mix"},
}


def model_case(name):
    module, cls = name.rsplit(".", 1)
    return getattr(import_module(module), cls), deepcopy(MODEL_DATA[name])


def control_case(name, field, kind):
    cls, data = model_case(name)
    value = cls.model_validate(data).model_dump(mode="python")[field]
    if kind == "omitted":
        data.pop(field, None)
    elif kind == "none":
        data[field] = None
    elif field == "profile_versions":
        versions = {"number": 1, "string": "1", "float": 1.0}
        if kind in versions:
            data[field] = (("voice", versions[kind]),)
        elif kind == "json_list":
            data[field] = [["voice", 1]]
        elif kind == "generator":
            data[field] = iter([("voice", 1)])
        elif kind == "bad_row":
            data[field] = [1]
        elif kind == "short_row":
            data[field] = [("voice",)]
        elif kind == "long_row":
            data[field] = [("voice", 1, "extra")]
        elif kind == "bad_container":
            data[field] = True
        else:
            raise AssertionError("unknown control")
    else:
        number = value if value is not None else 1.0
        data[field] = str(number) if kind == "string" else number
    return cls, data
