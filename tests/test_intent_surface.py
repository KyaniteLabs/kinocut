"""Intent router, b-roll proposals, caption translate, watching review."""

from __future__ import annotations

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
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n2\n00:00:02,000 --> 00:00:04,000\nThanks\n",
        encoding="utf-8",
    )
    result = translate_caption_file(str(srt), source_lang="en", target_lang="es")
    out = Path(result.output_path).read_text(encoding="utf-8").lower()
    assert "hola" in out or "mundo" in out or "gracias" in out
    assert result.cue_count == 2
    assert result.coverage["surfaces"]["dub"]["translation_applied"] is False


def test_translate_unsupported_pair_fails(tmp_path: Path) -> None:
    srt = tmp_path / "en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    with pytest.raises(MCPVideoError):
        translate_caption_file(str(srt), source_lang="en", target_lang="fr")


@pytest.mark.parametrize("installed", [False, True])
def test_language_coverage_principle(monkeypatch, installed) -> None:
    monkeypatch.setattr(
        "kinocut.intent.language_coverage.shutil.which", lambda _: "/candidate/espeak-ng" if installed else None
    )
    report = language_coverage_report()
    assert report["principle"].startswith("transcribe/translate/dub")
    assert report["surfaces"]["translate"]["available"] is True
    assert report["surfaces"]["dub"]["available"] is installed
    assert report["surfaces"]["dub"]["implemented_languages"] == ["en", "es"]
    assert report["surfaces"]["dub"]["supported_languages_or_pairs"] == (["en", "es"] if installed else [])


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


# --- roast-audit regressions: honest routing and translation ---------------------


def test_translate_never_rewrites_inside_a_word() -> None:
    from kinocut.intent.caption_translate import _default_translate

    assert _default_translate("Yesterday I said yes", "en", "es") == "Yesterday I said sí"
    assert _default_translate("Hello world", "en", "es") == "Hola mundo"


def test_translate_reports_how_much_of_the_source_it_left_untranslated(tmp_path: Path) -> None:
    srt = tmp_path / "en.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nI love the music today\n\n2\n00:00:02,000 --> 00:00:04,000\nKeep watching\n",
        encoding="utf-8",
    )
    result = translate_caption_file(str(srt), source_lang="en", target_lang="es")
    out = Path(result.output_path).read_text(encoding="utf-8")
    assert "música" in out and "hoy" in out and "Keep watching" in out
    assert (result.translated_words, result.total_words) == (2, 7)
    assert result.untranslated_cues == 1
    assert any("replaced 2 of 7 words" in warning for warning in result.warnings)
    payload = result.to_dict()
    assert payload["warnings"] == result.warnings
    assert payload["translated_words"] == 2


def test_broll_rejects_non_finite_or_negative_timestamps() -> None:
    for bad in (float("nan"), float("inf"), -1.0):
        with pytest.raises(MCPVideoError):
            propose_broll([{"start": bad, "end": 3.0, "text": "the music video"}])
    with pytest.raises(MCPVideoError):
        propose_broll([{"start": 0.0, "end": float("nan"), "text": "the music video"}])


def test_route_reformat_vertical_only_promises_what_video_resize_accepts() -> None:
    plan = route_intent("reformat_vertical")
    assert plan.compat_tools == ("video_resize",)
    assert plan.params == {"aspect_ratio": "9:16"}
    assert "subject_tracking" not in plan.summary


def test_route_remove_filler_is_declared_not_implemented_instead_of_misrouted() -> None:
    plan = route_intent("remove_filler")
    assert plan.next_action == "not_implemented"
    assert plan.compat_tools == ()
    assert plan.blocked_reason
    listed = next(verb for verb in list_intent_verbs() if verb["verb"] == "remove_filler")
    assert listed["next_action"] == "not_implemented"
    assert listed["blocked_reason"]
