from __future__ import annotations

from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product import shorts


def _segments() -> list[dict[str, object]]:
    texts = [
        "Here is the first complete explanation and why it matters.",
        "The second useful idea answers a practical question clearly.",
        "This demonstration reveals the result and explains the payoff.",
        "A fourth complete thought gives enough context to stand alone.",
        "The fifth moment emphasizes the lesson with a concrete example.",
        "This final answer closes the point without depending on later context.",
    ]
    return [
        {
            "segment_id": f"seg_{index:03d}",
            "start": index * 22.0,
            "end": index * 22.0 + 18.0,
            "text": text,
            "confidence": 0.95,
        }
        for index, text in enumerate(texts)
    ]


def test_raw_whisper_segment_keys_are_filtered():
    segments = shorts._segments(
        [
            {
                "id": 7,
                "seek": 0,
                "start": 1.0,
                "end": 3.0,
                "text": "A complete thought.",
                "tokens": [1, 2],
                "avg_logprob": -0.2,
            }
        ]
    )
    assert len(segments) == 1
    assert segments[0].segment_id == "seg_000000"
    assert segments[0].text == "A complete thought."


def test_transcribe_uses_longform_path_above_legacy_ceiling(monkeypatch):
    import kinocut.ai_engine.transcribe as ordinary
    import kinocut.ai_engine.transcribe_longform as longform

    class Segment:
        def model_dump(self, mode="json"):
            return {
                "start": 0.0,
                "end": 20.0,
                "text": "A complete long-form thought.",
                "chunk_index": 0,
            }

    monkeypatch.setattr(
        ordinary,
        "ai_transcribe",
        lambda *_args, **_kwargs: pytest.fail("legacy transcribe path used"),
    )
    monkeypatch.setattr(
        longform,
        "transcribe_longform",
        lambda *_args, **_kwargs: SimpleNamespace(segments=[Segment()]),
    )

    segments = shorts._transcribe("stream.mp4", duration=3601.0)
    assert segments[0].text == "A complete long-form thought."


@pytest.fixture
def planned(tmp_path, monkeypatch):
    source = tmp_path / "stream.mp4"
    source.write_bytes(b"real-media-placeholder")
    monkeypatch.setattr(
        shorts,
        "probe",
        lambda _path: SimpleNamespace(
            duration=3600.0,
            width=1920,
            height=1080,
            audio_codec="aac",
            format="mp4",
        ),
    )
    payload = shorts.shorts_plan(
        str(source),
        config={
            "transcript_segments": _segments(),
            "output_dir": str(tmp_path / "out"),
            "min_clip_seconds": 10.0,
            "max_clip_seconds": 60.0,
        },
    )
    return source, payload


def test_plan_inspects_and_stops_for_review(planned):
    source, payload = planned
    assert payload["status"] == "review_required"
    assert payload["external_posting"] is False
    assert payload["intake"]["source_path"] == str(source.resolve())
    assert len(payload["intake"]["source_sha256"]) == 64
    assert len(payload["proposals"]) >= 3
    assert payload["platforms"] == ["youtube-shorts", "instagram-reel"]
    assert payload["config"]["render"]["captions_editable"] is True
    assert payload["config"]["render"]["burned_captions"] is False


def test_plan_is_json_stable_and_resumable(planned):
    _source, payload = planned
    loaded = shorts.load_shorts_plan(payload["job_id"])
    assert loaded.model_dump(mode="json") == payload
    assert (loaded.output_dir + "/" + loaded.job_id + ".plan.json").endswith(".plan.json")


def test_render_requires_explicit_human_approval(planned, tmp_path):
    _source, payload = planned
    candidate_id = payload["proposals"][0]["candidate_id"]
    with pytest.raises(MCPVideoError) as exc:
        shorts.shorts_render(payload["job_id"], candidate_id, output_path=str(tmp_path / "render"))
    assert exc.value.code == "shorts_review_required"


def test_review_is_append_only_and_supports_editor_actions(planned):
    _source, payload = planned
    candidate_id = payload["proposals"][0]["candidate_id"]
    shorts.shorts_review(
        payload["job_id"],
        candidate_id,
        decision={
            "action": "trim",
            "start": payload["proposals"][0]["start"] + 0.5,
            "end": payload["proposals"][0]["end"] - 0.5,
        },
        evidence_ref="operator-review",
    )
    shorts.shorts_review(
        payload["job_id"],
        candidate_id,
        decision={"action": "title_hook_edit", "title": "Edited title", "hook": "Edited hook"},
        evidence_ref="operator-review",
    )
    result = shorts.shorts_review(payload["job_id"], candidate_id, decision="approve", evidence_ref="operator-review")
    assert [entry["action"] for entry in result["decisions"]][-3:] == [
        "trim",
        "title_hook_edit",
        "approve",
    ]


def test_reject_supersedes_prior_approval(planned, tmp_path):
    _source, payload = planned
    candidate_id = payload["proposals"][0]["candidate_id"]
    shorts.shorts_review(payload["job_id"], candidate_id, decision="approve", evidence_ref="review")
    shorts.shorts_review(payload["job_id"], candidate_id, decision="reject", evidence_ref="review")
    with pytest.raises(MCPVideoError) as exc:
        shorts.shorts_render(payload["job_id"], candidate_id, output_path=str(tmp_path / "render"))
    assert exc.value.code == "shorts_review_required"


def test_sensitive_unsuitable_candidate_cannot_render(planned, tmp_path):
    _source, payload = planned
    candidate_id = payload["proposals"][0]["candidate_id"]
    shorts.shorts_review(payload["job_id"], candidate_id, decision="approve", evidence_ref="review")
    shorts.shorts_review(
        payload["job_id"],
        candidate_id,
        decision={"action": "sensitive_unsuitable", "sensitive": True, "unsuitable": True},
        evidence_ref="review",
    )
    with pytest.raises(MCPVideoError) as exc:
        shorts.shorts_render(payload["job_id"], candidate_id, output_path=str(tmp_path / "render"))
    assert exc.value.code == "shorts_candidate_unsuitable"
