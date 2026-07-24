from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product.models import CandidateMoment, canonical_dedup_key
from kinocut.product.shorts_plan import ShortsPlan, save_shorts_plan
from kinocut.product.shorts_render import render_approved_candidate
from kinocut.product.shorts_review import review_shorts_plan


def _plan(tmp_path: Path, source: Path) -> str:
    excerpt = "A complete candidate thought."
    candidate = CandidateMoment(
        candidate_id="candidate_01",
        start=10.0,
        end=25.0,
        transcript_excerpt=excerpt,
        suggested_title="A useful clip",
        suggested_hook="Start here",
        rationale="Complete thought",
        confidence=0.9,
        dedup_key=canonical_dedup_key(start=10.0, end=25.0, excerpt=excerpt, sensitivity="none"),
    )
    plan_dir = tmp_path / "plans"
    save_shorts_plan(
        ShortsPlan.model_validate(
            {
                "job_id": "shorts_0123456789abcdef",
                "project_dir": str(tmp_path),
                "output_dir": str(plan_dir),
                "intake": {
                    "source_path": str(source),
                    "source_sha256": "a" * 64,
                    "duration": 60.0,
                    "width": 1920,
                    "height": 1080,
                    "audio_available": True,
                },
                "platforms": ("youtube-shorts", "instagram-reel"),
                "config": {"render": {"audio": {"lufs": -14.0, "fade_seconds": 0.05}}},
                "transcript": (
                    {"segment_id": "segment_01", "start": 10.0, "end": 25.0, "text": excerpt},
                ),
                "proposals": (candidate.model_dump(mode="json"),),
            }
        )
    )
    return str(plan_dir)


def _stub(monkeypatch, source: Path) -> None:
    def out(path, data=b"x"):
        Path(path).write_bytes(data)
        return SimpleNamespace(output_path=path)

    monkeypatch.setattr(
        "kinocut.product.shorts_render.trim",
        lambda *a, output_path=None, **k: out(output_path, b"trim"),
    )
    monkeypatch.setattr(
        "kinocut.product.shorts_render.resize",
        lambda *a, output_path=None, **k: out(output_path, b"resize"),
    )
    monkeypatch.setattr(
        "kinocut.product.shorts_render.normalize_audio",
        lambda *a, output_path=None, **k: out(output_path, b"norm"),
    )
    monkeypatch.setattr(
        "kinocut.product.shorts_render.thumbnail",
        lambda *a, output_path=None, **k: out(output_path, b"thumb"),
    )

    def run(cmd, **k):
        for item in reversed(cmd):
            if isinstance(item, str) and item.endswith(".mp4"):
                Path(item).write_bytes(b"ffmpeg")
                break
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("kinocut.product.shorts_render._run_ffmpeg", run)
    monkeypatch.setattr("kinocut.product.shorts_render._validate_input_path", lambda p: str(source))


def test_render_fails_closed_without_approve(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")
    with pytest.raises(MCPVideoError) as exc:
        render_approved_candidate(_plan(tmp_path, source), candidate_id="candidate_01")
    assert exc.value.code == "shorts_review_required"


def test_render_pipeline_records_both_platforms(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")
    plan = _plan(tmp_path, source)
    review_shorts_plan(plan, candidate_id="candidate_01", decision="approve")
    _stub(monkeypatch, source)
    result = render_approved_candidate(plan, candidate_id="candidate_01")
    assert result["status"] == "rendered"
    assert result["external_posting"] is False
    assert len(result["renders"]) == 2
    assert {r["platform"] for r in result["renders"]} == {"youtube-shorts", "instagram-reel"}
    again = render_approved_candidate(plan, candidate_id="candidate_01")
    assert all(item.get("cache_hit") for item in again["renders"])
