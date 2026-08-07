"""Intent router, b-roll proposals, caption translate, watching review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.intent import (
    language_coverage_report,
    list_intent_verbs,
    propose_broll,
    route_intent,
    translate_caption_file,
)
from kinocut.watching import ReviewPolicy, decide_review, run_review


def test_intent_catalog_has_at_least_eight_verbs() -> None:
    verbs = list_intent_verbs()
    assert len(verbs) >= 8
    names = {v["verb"] for v in verbs}
    assert "repurpose" in names
    assert "inject_broll" in names
    assert "find_moments" in names


def test_route_intent_inject_broll_is_propose_only() -> None:
    plan = route_intent("inject_broll", {"max_proposals": 3})
    assert plan.next_action == "propose_only"
    assert plan.mutates_media is False
    assert "video_propose_broll" in plan.compat_tools


def test_route_unknown_verb_fails() -> None:
    with pytest.raises(MCPVideoError):
        route_intent("do_magic_edit")


def test_broll_proposals_never_auto_accept() -> None:
    segments = [
        {"start": 0.0, "end": 2.5, "text": "Welcome to the music video today"},
        {"start": 3.0, "end": 5.0, "text": "um"},
    ]
    props = propose_broll(segments, max_proposals=5)
    assert props
    assert all(p.accepted is False for p in props)
    assert all(p.to_dict()["apply_policy"] == "human_review_required" for p in props)


def test_translate_captions_en_es(tmp_path: Path) -> None:
    srt = tmp_path / "en.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nThanks\n",
        encoding="utf-8",
    )
    result = translate_caption_file(str(srt), source_lang="en", target_lang="es")
    out = Path(result.output_path).read_text(encoding="utf-8").lower()
    assert "hola" in out or "mundo" in out or "gracias" in out
    assert result.cue_count == 2
    assert result.coverage["surfaces"]["dub"]["available"] is False


def test_translate_unsupported_pair_fails(tmp_path: Path) -> None:
    srt = tmp_path / "en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    with pytest.raises(MCPVideoError):
        translate_caption_file(str(srt), source_lang="en", target_lang="fr")


def test_language_coverage_principle() -> None:
    report = language_coverage_report()
    assert report["principle"].startswith("transcribe/translate/dub")
    assert report["surfaces"]["translate"]["available"] is True
    assert report["surfaces"]["dub"]["available"] is False


def test_review_run_and_decide() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "tests" / "fixtures" / "golden" / "workflow_final.mp4"
    if not path.is_file():
        pytest.skip("golden fixture missing")
    run = run_review(str(path), ReviewPolicy(min_duration_seconds=0.1))
    assert run.verdict in {"pass", "fail"}
    data = run.to_dict()
    if data["blocked"]:
        with pytest.raises(MCPVideoError):
            decide_review(data, "accept", reason="")
        dec = decide_review(data, "accept", reason="human override for test")
    else:
        dec = decide_review(data, "accept", reason="ok")
    assert dec.decision == "accept"
