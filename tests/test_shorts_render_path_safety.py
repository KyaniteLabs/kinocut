"""Path containment for shorts render/package stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product.models import CandidateMoment, TranscriptSegment, canonical_dedup_key
from kinocut.product.shorts_package import package_approved_candidate
from kinocut.product.shorts_plan import IntakeReport, ShortsPlan, save_shorts_plan
from kinocut.product.shorts_render import _safe_render_base
from kinocut.product.shorts_review import review_shorts_plan


def _plan(tmp_path: Path) -> ShortsPlan:
    project = tmp_path / "proj"
    out = project / "out"
    project.mkdir()
    out.mkdir()
    source = project / "src.mp4"
    source.write_bytes(b"not-a-real-video")
    start, end, excerpt, sensitivity = 1.0, 5.0, "hello world", "none"
    plan = ShortsPlan(
        job_id="shorts_" + ("a" * 16),
        project_dir=str(project),
        output_dir=str(out),
        intake=IntakeReport(
            source_path=str(source),
            source_sha256="b" * 64,
            duration=12.0,
            width=1920,
            height=1080,
            audio_available=True,
        ),
        platforms=("youtube-shorts",),
        config={},
        transcript=(
            TranscriptSegment(
                segment_id="s1",
                start=0.0,
                end=5.0,
                text="hello world",
                confidence=0.9,
            ),
        ),
        proposals=(
            CandidateMoment(
                candidate_id="c1",
                start=start,
                end=end,
                transcript_excerpt=excerpt,
                suggested_title="t",
                suggested_hook="h",
                rationale="test",
                confidence=0.8,
                sensitivity=sensitivity,
                unsuitable=False,
                dedup_key=canonical_dedup_key(start=start, end=end, excerpt=excerpt, sensitivity=sensitivity),
            ),
        ),
    )
    return save_shorts_plan(plan)


def test_safe_render_base_rejects_escape(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(MCPVideoError) as exc:
        _safe_render_base(plan, "c1", str(outside))
    assert getattr(exc.value, "code", None) == "unsafe_path" or "unsafe" in str(exc.value).lower()


def test_package_root_rejects_escape(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    out_dir = plan.output_dir
    review_shorts_plan(out_dir, candidate_id="c1", decision="approve")
    outside = tmp_path / "pkg-outside"
    outside.mkdir()
    with pytest.raises(MCPVideoError) as exc:
        package_approved_candidate(out_dir, candidate_id="c1", package_root=str(outside))
    code = getattr(exc.value, "code", "")
    assert code in {"unsafe_path", "shorts_package_render_required"}
