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


def test_audio_finishing_config_defaults_are_evidence_backed():
    """AudioFinishingConfig only exposes knobs the orchestrator actually threads through.

    The orchestrator's render path currently reads ``lufs`` (loudness
    target) and ``fade_seconds`` (clip-edge fade) and nothing else.
    Historical fields such as ``true_peak_dbtp``, ``declick_seconds``,
    ``noise_reduction_key``, and ``bypass_noise_reduction`` were
    silently inert because no consumer was wired up to act on them.
    ``extra="forbid"`` on the strict base now rejects them.
    """
    from kinocut.product.config import AudioFinishingConfig

    cfg = AudioFinishingConfig()
    assert cfg.lufs == -14.0
    assert cfg.fade_seconds == 0.05
    # The strict base rejects unknown fields; ensure the inert knobs
    # cannot sneak back in via the public surface.
    for inert_name in (
        "true_peak_dbtp",
        "declick_seconds",
        "noise_reduction_key",
        "bypass_noise_reduction",
    ):
        with pytest.raises(ValueError):
            AudioFinishingConfig(**{inert_name: -1.0})  # type: ignore[arg-type]


def test_audio_finishing_config_validates_lufs_bounds():
    """``lufs`` must stay inside the documented ``[-36, -6]`` window."""
    from kinocut.product.config import AudioFinishingConfig

    # In-range is preserved verbatim.
    cfg = AudioFinishingConfig(lufs=-23.0)
    assert cfg.lufs == -23.0
    # Out-of-range raises a pydantic ValidationError, which is exposed
    # to callers via the existing MCPVideoError surface.
    with pytest.raises(ValueError):
        AudioFinishingConfig(lufs=0.0)
    with pytest.raises(ValueError):
        AudioFinishingConfig(lufs=-40.0)
    # ``fade_seconds`` is clamped to ``[0, 2]`` for clip-edge safety.
    with pytest.raises(ValueError):
        AudioFinishingConfig(fade_seconds=-0.1)
    with pytest.raises(ValueError):
        AudioFinishingConfig(fade_seconds=3.0)


def test_render_audio_section_uses_only_evidence_backed_keys(planned):
    """The plan payload must only serialise the orchestrator-consumed audio knobs."""
    from kinocut.product.config import AudioFinishingConfig

    _source, payload = planned
    audio_section = payload["config"]["render"]["audio"]
    # The orchestrator's render path only honours ``lufs`` and
    # ``fade_seconds`` today; asserting on exact keys guards against
    # accidental re-introduction of inert knobs.
    assert set(audio_section.keys()) == {"lufs", "fade_seconds"}
    # The default config matches the orchestrator's documented defaults.
    assert audio_section == AudioFinishingConfig().model_dump(mode="json")


def test_shorts_config_rejects_inert_audio_fields(planned):
    """Inert audio-finishing fields are rejected at the strict pydantic layer."""
    from kinocut.product.config import config_from_mapping

    with pytest.raises(ValueError):
        config_from_mapping({"render": {"audio": {"noise_reduction_key": "highway"}}})
    with pytest.raises(ValueError):
        config_from_mapping({"render": {"audio": {"bypass_noise_reduction": False}}})
    with pytest.raises(ValueError):
        config_from_mapping({"render": {"audio": {"declick_seconds": 0.5}}})
    with pytest.raises(ValueError):
        config_from_mapping({"render": {"audio": {"true_peak_dbtp": -1.5}}})
