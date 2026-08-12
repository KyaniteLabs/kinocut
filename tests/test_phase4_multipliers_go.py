"""Phase 4 Multipliers formal GO suite."""

from __future__ import annotations

from pathlib import Path

from kinocut.multipliers import (
    export_otio_json,
    import_otio_json,
    plan_generative_last_mile,
    plan_tts_dub,
    write_review_surface,
)


def test_generative_local_default_and_paid_cap() -> None:
    local = plan_generative_last_mile("broll sky", provider="local", max_spend_usd=0.0, estimated_spend_usd=0.0)
    assert local.allowed is True or local.to_dict().get("allowed") is True
    paid = plan_generative_last_mile(
        "broll sky",
        provider="paid",
        max_spend_usd=0.0,
        estimated_spend_usd=1.5,
    )
    d = paid.to_dict() if hasattr(paid, "to_dict") else paid
    # paid above cap must not auto-execute
    assert d.get("allowed") is False or d.get("denied") is True or d.get("executable") is False


def test_otio_kinocut_ir_roundtrip_documented_scope(tmp_path: Path) -> None:
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
    exp = export_otio_json(timeline, str(out))
    assert exp["artifact_kind"] == "otio_export"
    assert out.is_file()
    imported = import_otio_json(str(out))
    assert imported["artifact_kind"] == "timeline_ir"
    assert imported["name"] == "demo"
    assert any(n["id"] == "c1" for n in imported["nodes"])
    # Interchange scope: kinocut_ir-embedded JSON, not foreign OTIO libraries


def test_review_ui_hot_reload_surface(tmp_path: Path) -> None:
    r = write_review_surface(str(tmp_path / "ui"))
    html = Path(r["html_path"])
    assert html.is_file()
    text = html.read_text(encoding="utf-8")
    assert "poll" in text.lower() or "reload" in text.lower() or "setInterval" in text


def test_tts_dub_es_first_not_translate() -> None:
    plan = plan_tts_dub("captions.srt", target_lang="es")
    d = plan if isinstance(plan, dict) else plan.to_dict()
    assert d.get("executable") is False
    assert d.get("artifact_kind") == "tts_dub_plan"
    assert d.get("target_lang") == "es"
    assert d.get("brand_primary") is True
