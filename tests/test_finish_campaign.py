"""Finish-campaign coverage: P3/P4/TE remaining surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.multipliers import (
    export_otio_json,
    import_otio_json,
    plan_generative_last_mile,
    plan_tts_dub,
    write_review_surface,
)
from kinocut.te import (
    frame_to_timestamp,
    generate_hook_candidates,
    plan_audiogram,
    plan_punch_zooms,
    session_open,
    session_step,
    validate_publish_spec,
)
from kinocut.timeline_ir import compile_ir_to_dag, parse_timeline_ir
from kinocut.watching import run_narrative_qc, run_vision_qc


def _minimal_ir() -> dict:
    return {
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


def test_timeline_ir_compile() -> None:
    ir = parse_timeline_ir(_minimal_ir())
    dag = compile_ir_to_dag(ir)
    assert ir.name == "demo"
    assert dag is not None


def test_otio_export_import(tmp_path: Path) -> None:
    out = tmp_path / "t.otio.json"
    export_otio_json(_minimal_ir(), str(out))
    back = import_otio_json(str(out))
    assert back["name"] == "demo"
    assert back["nodes"]


def test_generative_spend_cap() -> None:
    denied = plan_generative_last_mile("x", provider="openai", max_spend_usd=0.0, estimated_spend_usd=1.0)
    assert denied.allowed is False
    local = plan_generative_last_mile("x", provider="local")
    assert local.allowed is True


def test_review_ui(tmp_path: Path) -> None:
    r = write_review_surface(str(tmp_path))
    assert Path(r["html_path"]).is_file()


def test_tts_dub_plan_not_executable() -> None:
    p = plan_tts_dub("/tmp/cap.srt", target_lang="es")
    assert p["brand_primary"] is True
    assert "backend" in p
    # executable is True only when a doctor-visible TTS backend is present
    assert p["executable"] is bool(p["backend"].get("available"))


def test_publish_validate() -> None:
    ok = validate_publish_spec("youtube_shorts", duration_seconds=30, height=1920, width=1080)
    assert ok["verdict"] == "pass"
    bad = validate_publish_spec("youtube_shorts", duration_seconds=120, height=480, width=480)
    assert bad["blocked"] is True


def test_hooks_punch_seek_session(tmp_path: Path) -> None:
    hooks = generate_hook_candidates("agents", count=3, language="en")
    assert len(hooks["titles"]) == 3
    punch = plan_punch_zooms([1.0, 2.0])
    assert punch["event_count"] == 2
    seek = frame_to_timestamp(90, 30.0)
    assert abs(seek["seconds"] - 3.0) < 1e-6
    audio = plan_audiogram("/tmp/a.wav", chapter_marks=[0.0, 10.0])
    assert len(audio["chapters"]) == 2
    sess_dir = tmp_path / "sess"
    opened = session_open(str(sess_dir), "improve clarity")
    session_step(opened["path"], action="trim_silence", score=0.4)
    stepped2 = session_step(opened["path"], action="reframe", score=0.7)
    assert stepped2["measured_improvement"] == pytest.approx(0.3)


def test_vision_and_narrative_on_golden() -> None:
    root = Path(__file__).resolve().parents[1]
    media = root / "tests" / "fixtures" / "golden" / "workflow_final.mp4"
    if not media.is_file():
        return
    v = run_vision_qc(str(media))
    assert v["verdict"] in {"pass", "fail"}
    n = run_narrative_qc(str(media))
    assert "findings" in n
