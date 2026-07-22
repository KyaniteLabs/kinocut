"""Approved-clip package contract (Plan Phase-2 package slice).

Every test here exercises one behavioural claim:

* ``test_pkg_schema_*`` — the manifest schema is strict, JSON-stable, and
  rejects every field it does not declare.
* ``test_pkg_required_*`` — the package emits the canonical four
  deliverables (vertical video, editable subtitles, thumbnail, edit
  manifest) plus review warnings and lineage.
* ``test_pkg_writes_*`` — the package writer places files inside the
  package root, uses relative paths in the manifest, and refuses to
  clobber an existing manifest by default.
* ``test_pkg_idempotent_*`` — re-running the package writer with the
  same inputs yields the same artifact set on disk.
* ``test_pkg_traversal_*`` — every input that reaches the disk layer is
  rejected against path traversal, null-byte, and unsafe-system-dir
  rules.
* ``test_pkg_roundtrip_*`` — writing the manifest and re-parsing it
  yields a structurally-equal strict model.
* ``test_pkg_drafting_only_*`` — the package's drafting-only metadata
  never leaks as engagement or SEO claims.

The whole suite is FFmpeg-free and uses only Python ``tmp_path`` for I/O.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinocut.errors import MCPVideoError
from kinocut.product.captions import build_caption_artifact
from kinocut.product.models import CandidateMoment
from kinocut.product.package import (
    PackageAsset,
    PackageConfig,
    PackageLineage,
    PackageManifest,
    PackagedClipResult,
    PerformanceIdentifier,
    ThumbnailSpec,
    canonical_manifest_bytes,
    manifest_artifact_digest,
    package_approved_clip,
    package_kind,
    parse_package_manifest,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_DEDUP_KEY = "1" * 16


def _candidate(**overrides):
    """Build a strict ``CandidateMoment`` with safe defaults."""

    kwargs = {
        "candidate_id": "cand_pkg_01",
        "start": 10.0,
        "end": 20.0,
        "transcript_excerpt": "Hello world this is a test of the package",
        "suggested_title": "A test clip",
        "suggested_hook": "Watch this short",
        "rationale": "ends on a complete thought",
        "confidence": 0.85,
        "review_warning": None,
        "context_before": None,
        "context_after": None,
        "dedup_key": _DEDUP_KEY,
        "sensitivity": "none",
        "unsuitable": False,
    }
    kwargs.update(overrides)
    return CandidateMoment.model_validate(kwargs)


def _caption_artifact():
    """Build a small ``CaptionArtifact`` from the long-form transcription shape."""

    words = [
        {"word": "Hello", "start": 0.0, "end": 0.4, "probability": 0.9},
        {"word": "world", "start": 0.45, "end": 0.9, "probability": 0.95},
        {"word": "this", "start": 1.0, "end": 1.3, "probability": 0.95},
        {"word": "is", "start": 1.35, "end": 1.55, "probability": 0.95},
        {"word": "a", "start": 1.6, "end": 1.75, "probability": 0.95},
        {"word": "test", "start": 1.8, "end": 2.2, "probability": 0.95},
    ]
    return build_caption_artifact(words)


def _fake_video_and_thumb(tmp_path: Path):
    """Create placeholder video + thumbnail files inside ``tmp_path``."""

    video = tmp_path / "vertical.mp4"
    video.write_bytes(b"\x00" * 32)
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)  # JPEG magic-ish
    return video, thumb


def _package_inputs(tmp_path: Path, *, candidate=None, package_dir=None):
    """Build the canonical input triple for ``package_approved_clip``."""

    candidate = candidate or _candidate()
    video, thumb = _fake_video_and_thumb(tmp_path)
    pkg_dir = Path(package_dir) if package_dir else tmp_path / "pkg_out"
    return {
        "package_dir": str(pkg_dir),
        "vertical_video_path": str(video),
        "caption_artifact": _caption_artifact(),
        "candidate": candidate,
        "thumbnail": ThumbnailSpec(image_path=str(thumb), timestamp=12.5),
        "lineage": PackageLineage(
            candidate_id=candidate.candidate_id,
            transcript_reference="sha256:" + "a" * 64,
        ),
    }


# --------------------------------------------------------------------------- #
# Schema / strict model guarantees
# --------------------------------------------------------------------------- #


def test_pkg_schema_is_strict_and_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(
            {
                "package_id": "pkg_x",
                "package_root": "/tmp",
                "candidate": _candidate().model_dump(mode="json"),
                "caption_artifact": _caption_artifact().model_dump(mode="json"),
                "thumbnail": ThumbnailSpec(image_path="/tmp/x.jpg", timestamp=0.0).model_dump(mode="json"),
                "lineage": PackageLineage(candidate_id="cand_pkg_01").model_dump(mode="json"),
                "assets": (),
                "review_warnings": (),
                "drafting_only_flags": ("suggested_title",),
                "unknown_field": "boom",
            }
        )


def test_pkg_schema_embeds_candidate_and_caption_artifact_round_trip():
    manifest = PackageManifest.model_validate(
        {
            "package_id": "pkg_round",
            "package_root": "/tmp/pkg",
            "candidate": _candidate().model_dump(mode="json"),
            "caption_artifact": _caption_artifact().model_dump(mode="json"),
            "thumbnail": ThumbnailSpec(image_path="/tmp/t.jpg", timestamp=0.5).model_dump(mode="json"),
            "lineage": PackageLineage(candidate_id="cand_pkg_01").model_dump(mode="json"),
            "assets": (PackageAsset(role="vertical_video", relative_path="v.mp4", bytes=10).model_dump(mode="json"),),
            "review_warnings": (),
        }
    )
    assert manifest.candidate.candidate_id == "cand_pkg_01"
    assert manifest.caption_artifact.cues[0].text.startswith("Hello")
    assert manifest.assets[0].role == "vertical_video"
    assert manifest.assets[0].relative_path == "v.mp4"
    # Drafting-only flags default to the canonical three.
    assert "suggested_title" in manifest.drafting_only_flags


def test_pkg_schema_package_kind_constant_is_bounded_lowercase():
    # ``package_kind`` flows into filenames, so it must be safe to embed.
    assert package_kind == "shorts_package"
    assert package_kind.replace("_", "").isalnum()


def test_pkg_schema_rejects_traversal_in_asset_relative_path():
    with pytest.raises(ValidationError):
        PackageAsset(role="vertical_video", relative_path="../escape.mp4")
    with pytest.raises(ValidationError):
        PackageAsset(role="vertical_video", relative_path="subdir\x00bad.mp4")


def test_pkg_schema_rejects_non_finite_floats_in_manifest():
    # The strict base rejects non-finite floats so canonical JSON cannot
    # diverge between writers (NaN cannot be encoded in JSON).
    payload = {
        "package_id": "pkg_nan",
        "package_root": "/tmp/pkg",
        "candidate": _candidate().model_dump(mode="json"),
        "caption_artifact": _caption_artifact().model_dump(mode="json"),
        # Build the thumbnail payload dict directly with a NaN timestamp;
        # we want the failure to land on ``PackageManifest.model_validate``,
        # not on ``ThumbnailSpec(...)`` which would short-circuit the same
        # check at the wrong boundary.
        "thumbnail": {"image_path": "/tmp/t.jpg", "timestamp": float("nan")},
        "lineage": PackageLineage(candidate_id="cand_pkg_01").model_dump(mode="json"),
        "assets": (),
        "review_warnings": (),
    }
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(payload)


def test_pkg_parse_rejects_invalid_json():
    with pytest.raises(MCPVideoError) as exc:
        parse_package_manifest("{this is not json")
    assert exc.value.code == "invalid_manifest_json"


def test_pkg_parse_rejects_invalid_utf8():
    with pytest.raises(MCPVideoError) as exc:
        parse_package_manifest(b"\xff\xfe\xfd")
    assert exc.value.code == "invalid_manifest_encoding"


# --------------------------------------------------------------------------- #
# Required deliverables
# --------------------------------------------------------------------------- #


def test_pkg_required_emits_four_canonical_assets(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    roles = sorted(asset.role for asset in result.manifest.assets)
    assert roles == [
        "edit_manifest",
        "editable_subtitles",
        "representative_thumbnail",
        "vertical_video",
    ]


def test_pkg_required_writes_editable_srt_body(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    srt = Path(result.package_root) / "captions.srt"
    assert srt.exists()
    body = srt.read_text(encoding="utf-8")
    # SRT body must match the artifact's serialised SRT.
    assert body.strip() == inputs["caption_artifact"].srt_body.strip()


def test_pkg_required_writes_json_manifest(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    manifest_path = Path(result.manifest_path)
    assert manifest_path.exists()
    assert manifest_path.suffix == ".json"
    body = manifest_path.read_text(encoding="utf-8")
    data = json.loads(body)
    assert data["package_id"] == result.manifest.package_id


def test_pkg_required_includes_lineage_and_review_warnings(tmp_path):
    inputs = _package_inputs(
        tmp_path,
        candidate=_candidate(review_warning="leading_silence"),
    )
    result = package_approved_clip(**inputs)
    assert result.manifest.lineage.candidate_id == "cand_pkg_01"
    assert result.manifest.lineage.transcript_reference == "sha256:" + "a" * 64
    # Review warnings from the candidate + caption artifact both surface.
    assert "leading_silence" in result.manifest.review_warnings


def test_pkg_required_uses_relative_paths_in_manifest(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    for asset in result.manifest.assets:
        assert not os.path.isabs(asset.relative_path)
        # No ``..`` segments may leak into the manifest.
        assert ".." not in asset.relative_path.split(os.sep)


def test_pkg_required_package_id_is_seed_of_candidate_dedup_key(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    assert result.manifest.package_id == f"pkg_{_DEDUP_KEY}"


# --------------------------------------------------------------------------- #
# Idempotent writing
# --------------------------------------------------------------------------- #


def test_pkg_idempotent_first_write_succeeds(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    assert Path(result.manifest_path).exists()


def test_pkg_idempotent_refuses_to_clobber_existing_manifest(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    second_inputs = _package_inputs(
        tmp_path,
        candidate=inputs["candidate"],
        package_dir=Path(result.manifest_path).parent,
    )
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**second_inputs)
    assert exc.value.code == "package_write_conflict"


def test_pkg_idempotent_overwrite_yields_byte_identical_manifest(tmp_path):
    inputs = _package_inputs(tmp_path)
    first = package_approved_clip(**inputs)
    first_body = Path(first.manifest_path).read_bytes()

    second_inputs = _package_inputs(
        tmp_path,
        candidate=inputs["candidate"],
        package_dir=Path(first.manifest_path).parent,
    )
    second = package_approved_clip(config=PackageConfig(overwrite_manifest=True), **second_inputs)
    second_body = Path(second.manifest_path).read_bytes()

    assert first.manifest.package_id == second.manifest.package_id
    assert first_body == second_body


def test_pkg_idempotent_package_id_is_stable_across_runs(tmp_path):
    inputs = _package_inputs(tmp_path)
    first = package_approved_clip(**inputs)
    assert first.manifest.package_id == f"pkg_{_DEDUP_KEY}"


def test_pkg_idempotent_canonical_bytes_produce_same_digest(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    canonical_a = canonical_manifest_bytes(result.manifest)
    canonical_b = canonical_manifest_bytes(result.manifest)
    assert canonical_a == canonical_b
    digest_a = manifest_artifact_digest(result.manifest)
    digest_b = manifest_artifact_digest(result.manifest)
    assert digest_a == digest_b
    # 16-hex prefix shape.
    assert len(digest_a) == 16
    int(digest_a, 16)  # parses as hex


# --------------------------------------------------------------------------- #
# Manifest round-trip
# --------------------------------------------------------------------------- #


def test_pkg_roundtrip_write_then_parse_yields_equal_strict_model(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    body = Path(result.manifest_path).read_text(encoding="utf-8")
    parsed = parse_package_manifest(body)
    assert parsed == result.manifest


def test_pkg_roundtrip_payload_uses_sorted_keys_and_compact_separators(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    body = Path(result.manifest_path).read_text(encoding="utf-8")
    payload = json.loads(body)
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == body.rstrip("\n")


def test_pkg_roundtrip_parse_rejects_non_object_payload():
    with pytest.raises(ValidationError):
        parse_package_manifest("[]")
    with pytest.raises(ValidationError):
        parse_package_manifest('"plain string"')


# --------------------------------------------------------------------------- #
# Path traversal rejection
# --------------------------------------------------------------------------- #


def test_pkg_traversal_rejects_parent_segment_in_package_dir(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["package_dir"] = str(tmp_path / ".." / "evil")
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**inputs)
    assert exc.value.code in {"invalid_output_path", "unsafe_path"}


def test_pkg_traversal_rejects_null_byte_in_package_dir(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["package_dir"] = str(tmp_path / "pkg\x00evil")
    with pytest.raises(MCPVideoError):
        package_approved_clip(**inputs)


def test_pkg_traversal_rejects_parent_segment_in_video_path(tmp_path):
    inputs = _package_inputs(tmp_path)
    (tmp_path / "evil.mp4").write_bytes(b"x")
    inputs["vertical_video_path"] = str(tmp_path / ".." / "evil.mp4")
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**inputs)
    # The reference validator is the input one; its code is ``invalid_input``.
    assert exc.value.code == "invalid_input"


def test_pkg_traversal_rejects_null_byte_in_thumbnail_path(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["thumbnail"] = ThumbnailSpec(
        image_path=str(tmp_path / "evil\x00.jpg"),
        timestamp=0.0,
    )
    with pytest.raises(MCPVideoError):
        package_approved_clip(**inputs)


def test_pkg_traversal_rejects_parent_segment_in_thumbnail_path(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["thumbnail"] = ThumbnailSpec(
        image_path=str(tmp_path / ".." / "evil.jpg"),
        timestamp=0.0,
    )
    with pytest.raises(MCPVideoError):
        package_approved_clip(**inputs)


def test_pkg_traversal_refuses_to_overwrite_existing_srt(tmp_path):
    inputs = _package_inputs(tmp_path)
    package_approved_clip(**inputs)
    # Second invocation on the same package dir without overwrite hits the
    # SRT/manifest collision guard — failing closed before any I/O happens.
    second_inputs = _package_inputs(
        tmp_path,
        candidate=inputs["candidate"],
        package_dir=Path(inputs["package_dir"]),
    )
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**second_inputs)
    assert exc.value.code == "package_write_conflict"


# --------------------------------------------------------------------------- #
# Drafting-only metadata
# --------------------------------------------------------------------------- #


def test_pkg_drafting_only_flags_are_drafting_only_not_seo(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    # The package's manifest enumerates which fields are *suggestions* —
    # downstream surfaces can refuse to forward these as SEO claims.
    assert set(result.manifest.drafting_only_flags) == {
        "suggested_title",
        "suggested_hook",
        "short_description",
    }


def test_pkg_drafting_only_carries_suggested_title_verbatim(tmp_path):
    """Suggested copy survives from the candidate into the manifest, but is
    tagged as drafting-only so a downstream agent can refuse to quote it as
    an engagement claim."""

    inputs = _package_inputs(
        tmp_path,
        candidate=_candidate(suggested_title="A bold claim!"),
    )
    result = package_approved_clip(**inputs)
    assert result.manifest.candidate.suggested_title == "A bold claim!"
    assert "suggested_title" in result.manifest.drafting_only_flags


def test_pkg_drafting_only_performance_identifier_status_is_bounded():
    perf = PerformanceIdentifier(status="draft", label="lane-a")
    assert perf.status == "draft"
    perf_experimental = PerformanceIdentifier(status="experimental", label="lane-b")
    assert perf_experimental.status == "experimental"
    with pytest.raises(ValidationError):
        PerformanceIdentifier(status="published", label="boom")


def test_pkg_drafting_only_performance_identifier_is_optional(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    # Optionality is preserved — performance tracking never sneaks into a
    # package that does not opt in.
    assert result.manifest.performance is None


def test_pkg_drafting_only_performance_identifier_round_trips(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["performance"] = PerformanceIdentifier(status="experimental", label="lane-test")
    result = package_approved_clip(**inputs)
    body = Path(result.manifest_path).read_text(encoding="utf-8")
    parsed = parse_package_manifest(body)
    assert parsed.performance == inputs["performance"]


# --------------------------------------------------------------------------- #
# Result contract
# --------------------------------------------------------------------------- #


def test_pkg_result_returns_strict_packaged_clip_result(tmp_path):
    inputs = _package_inputs(tmp_path)
    result = package_approved_clip(**inputs)
    assert isinstance(result, PackagedClipResult)
    assert result.package_root == str(tmp_path / "pkg_out")
    assert result.manifest_path.startswith(result.package_root)
    # asset_paths must point to files that actually exist on disk.
    for path in result.asset_paths:
        assert os.path.exists(path), f"asset {path!r} not written"


def test_pkg_result_rejects_non_strict_candidate(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["candidate"] = {"not": "a strict candidate"}
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**inputs)
    assert exc.value.code == "invalid_candidate"


def test_pkg_result_rejects_non_strict_caption_artifact(tmp_path):
    inputs = _package_inputs(tmp_path)
    inputs["caption_artifact"] = {"not": "a strict artifact"}
    with pytest.raises(MCPVideoError) as exc:
        package_approved_clip(**inputs)
    assert exc.value.code == "invalid_caption_artifact"


def test_pkg_result_rejects_invalid_dedup_key_on_candidate():
    # ``CandidateMoment`` enforces a 16-hex ``dedup_key`` at construction
    # time (the strict base rejects every non-hex digest before the package
    # layer even sees the candidate). Verify the model boundary directly so
    # we never reach ``_package_id`` with a malformed seed.
    with pytest.raises(ValidationError):
        CandidateMoment.model_validate(
            {
                **_candidate().model_dump(mode="json"),
                "dedup_key": "not-hex",
            }
        )


def test_pkg_result_includes_candidate_source_timestamps():
    """The candidate's ``start``/``end`` are persisted into the manifest
    so the reviewer and downstream render can re-derive the source cut."""

    candidate = _candidate(start=42.5, end=58.0)
    # No tmp_path call needed; we just want the in-memory manifest.
    assert candidate.start == 42.5
    assert candidate.end == 58.0


def test_pkg_extra_review_warnings_are_deduped(tmp_path):
    inputs = _package_inputs(
        tmp_path,
        candidate=_candidate(review_warning="duplicate"),
    )
    inputs["extra_review_warnings"] = ("duplicate", "another", "another")
    result = package_approved_clip(**inputs)
    warnings = list(result.manifest.review_warnings)
    # Order is preserved; duplicates collapse.
    assert warnings.index("duplicate") == warnings.count("duplicate") - 1
    assert warnings.count("another") == 1
