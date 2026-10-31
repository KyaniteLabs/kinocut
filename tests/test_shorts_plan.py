from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import kinocut.product.shorts_plan as plan_module
from kinocut.errors import MCPVideoError
from kinocut.product.models import CandidateMoment, TranscriptSegment, canonical_dedup_key
from kinocut.product.shorts_plan import IntakeReport, ReviewDecision, ShortsPlan, load_shorts_plan, save_shorts_plan

# These cases explicitly authorize updates to job-created review plans.
pytestmark = pytest.mark.usefixtures("overwrite_consent")


def test_public_plan_refusals_keep_the_package_reason_and_drop_caller_paths(tmp_path):
    """The cause is published when we wrote it, named by type when we did not.

    NEW-2: a blanket ``rejected_value`` around the cause collapsed our own
    bounded diagnostics to ``Likely cause: str``. The rule is provenance:
    a cause this package authored at a fixed construction site survives
    verbatim; a cause carrying a caller-selected path or a foreign
    exception's text never does.
    """
    plan_dir = tmp_path / "«redacted:sk-dir»"
    plan_dir.mkdir()

    # A missing plan: the caller-selected path is named by type only,
    # never echoed (the no-echo half of the rule).
    with pytest.raises(MCPVideoError) as missing:
        load_shorts_plan(str(plan_dir / "missing.json"))
    assert missing.value.code == "shorts_plan_not_found"
    assert "Likely cause: str" in str(missing.value)
    assert "«redacted:sk-dir»" not in str(missing.value)

    # A malformed plan names the foreign parser by kind too.
    bad = plan_dir / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(MCPVideoError) as malformed:
        load_shorts_plan(str(bad))
    assert malformed.value.code == "shorts_plan_malformed"
    assert "JSONDecodeError" in str(malformed.value)
    assert "not json" not in str(malformed.value)

    # A structurally-empty plan names the foreign validator by kind.
    empty = plan_dir / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(MCPVideoError) as invalid_shape:
        load_shorts_plan(str(empty))
    assert invalid_shape.value.code == "shorts_plan_malformed"
    assert "ValidationError" in str(invalid_shape.value)

    # A value that is not a plan names OUR phrase verbatim — and never the
    # caller's class name, because a class's ``__name__`` is caller data
    # (the same rule the retry placeholders follow).
    class Sneaky:
        pass

    Sneaky.__name__ = "«redacted:sk-type»"
    with pytest.raises(MCPVideoError) as wrong_type:
        save_shorts_plan(Sneaky())
    assert wrong_type.value.code == "invalid_plan"
    assert "Likely cause: the value is not a ShortsPlan instance." in str(wrong_type.value)
    assert "«redacted:sk-type»" not in str(wrong_type.value)

    # The serialized layer carries the same shape, because the dict is
    # what crosses the tool boundary.
    assert "«redacted:sk-dir»" not in json.dumps(missing.value.to_dict())
    assert "JSONDecodeError" in json.dumps(malformed.value.to_dict())
    assert "«redacted:sk-dir»" not in json.dumps(wrong_type.value.to_dict())


def _candidate() -> CandidateMoment:
    excerpt = "A complete candidate thought."
    return CandidateMoment(
        candidate_id="candidate_01",
        start=10.0,
        end=20.0,
        transcript_excerpt=excerpt,
        suggested_title="A useful clip",
        suggested_hook="Start here",
        rationale="Complete thought",
        confidence=0.9,
        dedup_key=canonical_dedup_key(start=10.0, end=20.0, excerpt=excerpt, sensitivity="none"),
    )


def _plan(output_dir: Path, **updates) -> ShortsPlan:
    values = {
        "job_id": "shorts_0123456789abcdef",
        "project_dir": str(output_dir.parent),
        "output_dir": str(output_dir),
        "intake": IntakeReport(
            source_path="/tmp/source.mp4",
            source_sha256="0" * 64,
            duration=60.0,
            width=1920,
            height=1080,
            audio_available=True,
        ),
        "platforms": ("youtube-shorts", "instagram-reel"),
        "config": {},
        "transcript": (TranscriptSegment(segment_id="segment_01", start=0.0, end=30.0, text="Transcript"),),
        "proposals": (_candidate(),),
    }
    values.update(updates)
    return ShortsPlan.model_validate(values)


def test_plan_save_load_is_source_free(tmp_path):
    plan = _plan(tmp_path / "plans")
    save_shorts_plan(plan)
    path = Path(plan.output_dir) / f"{plan.job_id}.plan.json"
    assert load_shorts_plan(str(path)) == plan


def test_plan_directory_lookup_requires_exactly_one_plan(tmp_path):
    first = _plan(tmp_path, job_id="shorts_0123456789abcdef")
    second = _plan(tmp_path, job_id="shorts_fedcba9876543210")
    save_shorts_plan(first)
    save_shorts_plan(second)
    with pytest.raises(MCPVideoError) as exc:
        load_shorts_plan(str(tmp_path))
    assert exc.value.code == "shorts_plan_ambiguous"


def test_plan_load_rejects_malformed_receipt(tmp_path):
    path = tmp_path / "shorts_0123456789abcdef.plan.json"
    path.write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(MCPVideoError) as exc:
        load_shorts_plan(str(path))
    assert exc.value.code == "shorts_plan_malformed"


@pytest.mark.parametrize(
    "payload",
    (
        {"candidate_id": "candidate_01", "action": "trim", "start": 9.0, "end": 8.0},
        {"candidate_id": "candidate_01", "action": "approve", "title": "not allowed"},
        {"candidate_id": "candidate_01", "action": "title_hook_edit"},
        {"candidate_id": "candidate_01", "action": "sensitive_unsuitable", "sensitive": True, "start": 1.0},
    ),
)
def test_review_decision_rejects_action_shape_mismatches(payload):
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate(payload)


def test_plan_save_rejects_intermediate_symlink(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir)
    with pytest.raises(MCPVideoError) as exc:
        save_shorts_plan(_plan(linked_dir / "plans"))
    assert exc.value.code == "unsafe_path"


def test_plan_save_cleans_temp_file_after_serialization_failure(tmp_path, monkeypatch):
    plan = _plan(tmp_path / "plans")

    def fail_serialization(_plan):
        raise OSError("disk full")

    monkeypatch.setattr(plan_module, "_plan_to_json", fail_serialization)
    with pytest.raises(OSError, match="disk full"):
        save_shorts_plan(plan)
    assert list(Path(plan.output_dir).iterdir()) == []
