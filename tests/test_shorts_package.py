from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product.models import CandidateMoment, canonical_dedup_key
from kinocut.product.shorts_package import package_approved_candidate
from kinocut.product.shorts_plan import RenderRecord, ShortsPlan, save_shorts_plan
from kinocut.product.shorts_review import review_shorts_plan


def _candidate() -> CandidateMoment:
    excerpt = "A complete candidate thought."
    return CandidateMoment(
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


def _plan_with_renders(tmp_path: Path) -> str:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    plan_dir = tmp_path / "plans"
    candidate = _candidate()
    renders = []
    for platform in ("youtube-shorts", "instagram-reel"):
        platform_dir = tmp_path / "renders" / platform
        platform_dir.mkdir(parents=True)
        video = platform_dir / "vertical.mp4"
        thumb = platform_dir / "thumbnail.jpg"
        srt = platform_dir / "captions.srt"
        video.write_bytes(f"video-{platform}".encode())
        thumb.write_bytes(f"thumb-{platform}".encode())
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        renders.append(
            RenderRecord(
                candidate_id=candidate.candidate_id,
                platform=platform,
                output_path=str(video),
                render_digest="a" * 16,
                editable_subtitles=str(srt),
                thumbnail_path=str(thumb),
            )
        )
    save_shorts_plan(
        ShortsPlan.model_validate(
            {
                "job_id": "shorts_0123456789abcdef",
                "project_dir": str(tmp_path),
                "output_dir": str(plan_dir),
                "intake": {
                    "source_path": str(source),
                    "source_sha256": "b" * 64,
                    "duration": 60.0,
                    "width": 1920,
                    "height": 1080,
                    "audio_available": True,
                },
                "platforms": ("youtube-shorts", "instagram-reel"),
                "config": {},
                "transcript": (
                    {"segment_id": "segment_01", "start": 10.0, "end": 25.0, "text": "A complete candidate thought."},
                ),
                "proposals": (candidate.model_dump(mode="json"),),
                "renders": [item.model_dump(mode="json") for item in renders],
            }
        )
    )
    return str(plan_dir)


def test_package_fails_closed_without_approve(tmp_path):
    plan = _plan_with_renders(tmp_path)
    with pytest.raises(MCPVideoError) as exc:
        package_approved_candidate(plan, candidate_id="candidate_01")
    assert exc.value.code == "shorts_review_required"


def test_package_writes_both_platform_packages(tmp_path):
    plan = _plan_with_renders(tmp_path)
    review_shorts_plan(plan, candidate_id="candidate_01", decision="approve")
    result = package_approved_candidate(plan, candidate_id="candidate_01")
    assert result["status"] == "packaged"
    assert result["external_posting"] is False
    assert len(result["packages"]) == 2
    platforms = {item["platform"] for item in result["packages"]}
    assert platforms == {"youtube-shorts", "instagram-reel"}
    for item in result["packages"]:
        root = Path(item["package_root"])
        assert (root / "vertical.mp4").is_file()
        assert (root / "captions.srt").is_file()
        assert (root / "thumbnail.jpg").is_file()
        assert (root / "metadata.json").is_file()
        assert Path(item["manifest_path"]).is_file()
