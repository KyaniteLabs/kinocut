"""Wishlist + optional depth closeout tests (sequence shortcut, logging, OTIO foreign, generative gate)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from kinocut.engine_timeline import expand_sequence_shortcut
from kinocut.errors import MCPVideoError
from kinocut.multipliers import (
    assert_generative_executable,
    detect_tts_backend,
    export_otio_json,
    import_otio_json,
    plan_generative_last_mile,
    plan_tts_dub,
)
from kinocut.te import frame_to_timestamp, timestamp_to_frame
from kinocut.watching import run_vision_qc


def test_expand_sequence_shortcut_builds_tracks() -> None:
    raw = {
        "clips": ["a.mp4", "b.mp4", "c.mp4"],
        "transitions": ["fade", "dissolve"],
        "transition_duration": 0.5,
    }
    expanded = expand_sequence_shortcut(raw)
    assert "tracks" in expanded
    track = expanded["tracks"][0]
    assert track["type"] == "video"
    assert len(track["clips"]) == 3
    assert track["clips"][0]["source"] == "a.mp4"
    assert len(track["transitions"]) == 2
    assert track["transitions"][0]["type"] == "fade"
    assert track["transitions"][0]["after_clip"] == 0
    assert track["transitions"][1]["type"] == "dissolve"
    assert track["transitions"][0]["duration"] == 0.5


def test_expand_sequence_shortcut_repeats_last_transition() -> None:
    raw = {"clips": ["a.mp4", "b.mp4", "c.mp4", "d.mp4"], "transitions": ["fade"]}
    expanded = expand_sequence_shortcut(raw)
    types = [t["type"] for t in expanded["tracks"][0]["transitions"]]
    assert types == ["fade", "fade", "fade"]


def test_expand_sequence_shortcut_leaves_full_timeline() -> None:
    full = {"tracks": [{"type": "video", "clips": [{"source": "x.mp4"}]}]}
    assert expand_sequence_shortcut(full) is full


def test_expand_sequence_shortcut_rejects_empty() -> None:
    with pytest.raises(MCPVideoError, match="clips"):
        expand_sequence_shortcut({"clips": []})


def test_frame_accurate_seek_helpers() -> None:
    s = frame_to_timestamp(90, 30.0)
    assert abs(s["seconds"] - 3.0) < 1e-9
    assert "ffmpeg_ss" in s
    f = timestamp_to_frame(3.0, 30.0)
    assert f["frame"] == 90


def test_configure_logging_to_file(tmp_path: Path) -> None:
    from kinocut.__main__ import _configure_logging

    log_path = tmp_path / "kinocut.log"
    # Clear handlers so basicConfig-like attach is isolated
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for h in list(root.handlers):
            root.removeHandler(h)
        _configure_logging(verbose=False, log_file=str(log_path))
        logging.getLogger("kinocut.test").debug("hello-depth-closeout")
        for h in list(root.handlers):
            h.flush()
        text = log_path.read_text(encoding="utf-8")
        assert "hello-depth-closeout" in text
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for h in before:
            root.addHandler(h)


def test_generative_paid_path_rigor() -> None:
    denied = plan_generative_last_mile("x", provider="openai", max_spend_usd=0.0, estimated_spend_usd=0.5)
    assert denied.allowed is False
    assert denied.executable is False
    assert denied.paid_path is True
    with pytest.raises(MCPVideoError, match="not executable"):
        assert_generative_executable(denied)

    allowed = plan_generative_last_mile(
        "x", provider="openai", max_spend_usd=2.0, estimated_spend_usd=0.5
    )
    assert allowed.allowed is True
    assert allowed.executable is True
    assert assert_generative_executable(allowed)["provider"] == "openai"

    local = plan_generative_last_mile("x", provider="local")
    assert local.local_only is True
    assert local.executable is True


def test_tts_backend_probe_shape() -> None:
    backend = detect_tts_backend()
    assert "available" in backend
    assert "backends" in backend
    plan = plan_tts_dub("captions.srt", target_lang="es")
    assert plan["artifact_kind"] == "tts_dub_plan"
    assert plan["brand_primary"] is True
    assert "backend" in plan
    assert plan["executable"] is bool(backend["available"])


def test_foreign_otio_local_media_import(tmp_path: Path, sample_video: str) -> None:
    doc = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": "foreign_demo",
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "V1",
                    "kind": "Video",
                    "children": [
                        {
                            "OTIO_SCHEMA": "Clip.1",
                            "name": "shot_a",
                            "media_reference": {
                                "OTIO_SCHEMA": "ExternalReference.1",
                                "target_url": f"file://{sample_video}",
                            },
                        }
                    ],
                }
            ],
        },
    }
    path = tmp_path / "foreign.otio.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    imported = import_otio_json(str(path))
    assert imported["artifact_kind"] == "foreign_otio_import"
    assert imported["import_mode"] == "foreign_local_media"
    assert imported["name"] == "foreign_demo"
    assert imported["clip_count"] == 1
    assert imported["clips"][0]["id"] == "shot_a"
    assert "sequence_shortcut" in imported
    assert len(imported["sequence_shortcut"]["clips"]) == 1


def test_foreign_otio_remote_rejected(tmp_path: Path) -> None:
    doc = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": "remote",
        "tracks": {
            "children": [
                {
                    "children": [
                        {
                            "name": "bad",
                            "media_reference": {"target_url": "https://example.com/a.mp4"},
                        }
                    ]
                }
            ]
        },
    }
    path = tmp_path / "remote.otio.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(MCPVideoError, match="local media"):
        import_otio_json(str(path))


def test_otio_kinocut_ir_still_preferred(tmp_path: Path) -> None:
    timeline = {
        "ir_schema_version": 1,
        "name": "demo",
        "timebase": {"numerator": 1, "denominator": 30},
        "sources": {"s1": {"path": "media/in.mp4"}},
        "nodes": [
            {
                "id": "c1",
                "kind": "clip",
                "depends_on": [],
                "inputs": {"src": "@sources.s1"},
                "params": {
                    "start": {"numerator": 0, "denominator": 1},
                    "duration": {"numerator": 30, "denominator": 1},
                },
                "output": "@outputs.final",
            }
        ],
        "outputs": {"final": {"path": "out/final.mp4"}},
    }
    out = tmp_path / "demo.otio.json"
    export_otio_json(timeline, str(out))
    imported = import_otio_json(str(out))
    assert imported["import_mode"] == "kinocut_ir"
    assert imported["name"] == "demo"


def test_vision_qc_structural_keyframes(sample_video: str) -> None:
    result = run_vision_qc(sample_video, sample_times=[0.1], require_vlm=False)
    assert result["artifact_kind"] == "vision_qc"
    assert result["verdict"] in {"pass", "fail"}
    assert "keyframe_count" in result
    # At least attempted structural sample
    assert any(f["check_id"] == "vision.keyframe_sample" for f in result["findings"])
