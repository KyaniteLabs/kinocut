from kinocut.product.shorts_plan import RenderRecord, ShortsPlan
from kinocut.product.models import CandidateMoment, canonical_dedup_key


def test_plan_accepts_render_records_with_defaults(tmp_path):
    excerpt = "A complete candidate thought."
    candidate = CandidateMoment(
        candidate_id="candidate_01",
        start=1.0,
        end=10.0,
        transcript_excerpt=excerpt,
        suggested_title="T",
        suggested_hook="H",
        rationale="R",
        confidence=0.5,
        dedup_key=canonical_dedup_key(start=1.0, end=10.0, excerpt=excerpt, sensitivity="none"),
    )
    plan = ShortsPlan.model_validate(
        {
            "job_id": "shorts_0123456789abcdef",
            "project_dir": str(tmp_path),
            "output_dir": str(tmp_path),
            "intake": {
                "source_path": "/tmp/a.mp4",
                "source_sha256": "b" * 64,
                "duration": 20.0,
                "width": 1,
                "height": 1,
                "audio_available": True,
            },
            "platforms": ("youtube-shorts",),
            "config": {},
            "transcript": ({"segment_id": "segment_01", "start": 0.0, "end": 5.0, "text": "hi"},),
            "proposals": (candidate.model_dump(mode="json"),),
            "renders": (
                {
                    "candidate_id": "candidate_01",
                    "platform": "youtube-shorts",
                    "output_path": "/tmp/out.mp4",
                    "render_digest": "0" * 16,
                    "editable_subtitles": "/tmp/c.srt",
                    "thumbnail_path": "/tmp/t.jpg",
                },
            ),
        }
    )
    assert len(plan.renders) == 1
    assert plan.external_posting is False
    assert isinstance(plan.renders[0], RenderRecord)
