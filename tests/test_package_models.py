from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kinocut.errors import MCPVideoError
from kinocut.product import (
    PackagedClipResult,
    PackageAsset,
    PackageLineage,
    ShortsPackageManifest,
    PerformanceIdentifier,
    ThumbnailSpec,
    canonical_manifest_bytes,
    manifest_artifact_digest,
    parse_package_manifest,
)
from kinocut.product.captions import CaptionArtifact, build_caption_artifact
from kinocut.product.models import CandidateMoment, canonical_dedup_key


def _candidate(**overrides) -> CandidateMoment:
    base = {
        "candidate_id": "cand_pkg_01",
        "start": 10.0,
        "end": 20.0,
        "transcript_excerpt": "Hello world this is a test of the package",
        "suggested_title": "A test clip",
        "suggested_hook": "Watch this short",
        "rationale": "ends on a complete thought",
        "confidence": 0.85,
        "sensitivity": "none",
    }
    base.update(overrides)
    base["dedup_key"] = canonical_dedup_key(
        start=base["start"],
        end=base["end"],
        excerpt=base["transcript_excerpt"],
        sensitivity=base["sensitivity"],
    )
    return CandidateMoment.model_validate(base)


def _caption_artifact() -> CaptionArtifact:
    return build_caption_artifact(
        [
            {"word": "Hello", "start": 0.0, "end": 0.4, "probability": 0.9},
            {"word": "world", "start": 0.45, "end": 0.9, "probability": 0.95},
            {"word": "this", "start": 1.0, "end": 1.3, "probability": 0.95},
            {"word": "is", "start": 1.35, "end": 1.55, "probability": 0.95},
            {"word": "a", "start": 1.6, "end": 1.75, "probability": 0.95},
            {"word": "test", "start": 1.8, "end": 2.2, "probability": 0.95},
        ]
    )


def _manifest_inputs(**overrides) -> dict:
    inputs = {
        "package_id": "pkg_test",
        "package_root": "/tmp/pkg_test",
        "candidate": _candidate().model_dump(mode="json"),
        "caption_artifact": _caption_artifact().model_dump(mode="json"),
        "thumbnail": ThumbnailSpec(image_path="/tmp/t.jpg", timestamp=12.5).model_dump(mode="json"),
        "lineage": PackageLineage(candidate_id="cand_pkg_01").model_dump(mode="json"),
        "assets": (PackageAsset(role="vertical_video", relative_path="v.mp4", bytes=10).model_dump(mode="json"),),
        "review_warnings": (),
    }
    inputs.update(overrides)
    return inputs


def _manifest(**overrides) -> ShortsPackageManifest:
    return ShortsPackageManifest.model_validate(_manifest_inputs(**overrides))


def test_pkg_strict_manifest_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ShortsPackageManifest.model_validate({**_manifest_inputs(), "unknown_field": "boom"})


def test_pkg_strict_manifest_rejects_non_finite_floats():
    payload = _manifest_inputs(thumbnail={"image_path": "/tmp/t.jpg", "timestamp": float("nan")})
    with pytest.raises(ValidationError):
        ShortsPackageManifest.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    ("../escape.mp4", "oops\\..\\bad.srt", "/etc/passwd", "C:\\secret.mp4", "\\\\server\\share", "bad\nname"),
)
def test_pkg_asset_rejects_paths_that_escape_or_corrupt_package(path):
    with pytest.raises(ValidationError):
        PackageAsset(role="vertical_video", relative_path=path)


def test_pkg_traversal_manifest_rejects_traversal_in_asset_tuple():
    inputs = _manifest_inputs(
        assets=(
            {"role": "vertical_video", "relative_path": "ok.mp4", "bytes": 4},
            {"role": "editable_subtitles", "relative_path": "oops/../bad.srt", "bytes": 4},
        )
    )
    with pytest.raises(ValidationError):
        ShortsPackageManifest.model_validate(inputs)


def test_pkg_manifest_rejects_noncanonical_package_kind():
    with pytest.raises(ValidationError):
        _manifest(package_kind="production_final")


@pytest.mark.parametrize("version", (True, 1.0, "1"))
def test_pkg_manifest_rejects_coerced_schema_version(version):
    with pytest.raises(ValidationError):
        _manifest(schema_version=version)


def test_pkg_roundtrip_canonical_bytes_use_sorted_keys_and_compact_separators():
    encoded = canonical_manifest_bytes(_manifest()).decode("utf-8")
    assert json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":")) == encoded


def test_pkg_roundtrip_parse_bytes_payload_matches_structural_copy():
    assert parse_package_manifest(canonical_manifest_bytes(_manifest())) == _manifest()


def test_pkg_roundtrip_parse_text_payload_matches_structural_copy():
    encoded = canonical_manifest_bytes(_manifest()).decode("utf-8")
    assert parse_package_manifest(encoded) == _manifest()


def test_pkg_digest_is_stable_and_16_hex():
    d = manifest_artifact_digest(_manifest())
    assert d == manifest_artifact_digest(_manifest()) and len(d) == 16 and int(d, 16) >= 0


def test_pkg_digest_changes_when_semantic_content_changes():
    assert manifest_artifact_digest(_manifest(review_warnings=("alpha",))) != manifest_artifact_digest(
        _manifest(review_warnings=("beta",))
    )


def test_pkg_drafting_only_flags_default_to_three_canonical_tags():
    assert set(_manifest().drafting_only_flags) == {
        "suggested_title",
        "suggested_hook",
        "short_description",
    }


def test_pkg_drafting_only_performance_status_accepts_canonical_values():
    assert PerformanceIdentifier(status="draft", label="lane-a").status == "draft"
    assert PerformanceIdentifier(status="experimental", label="lane-b").status == "experimental"


def test_pkg_drafting_only_performance_status_rejects_non_canonical_value():
    with pytest.raises(ValidationError):
        PerformanceIdentifier(status="published", label="boom")


def test_pkg_result_packaged_clip_result_round_trips_via_json():
    m = _manifest()
    result = PackagedClipResult(
        package_root="/tmp/pkg",
        manifest_path="/tmp/pkg/manifest.json",
        asset_paths=("/tmp/pkg/v.mp4", "/tmp/pkg/manifest.json"),
        manifest=m,
    )
    assert PackagedClipResult.model_validate(result.model_dump(mode="json")) == result


def test_pkg_parse_rejects_invalid_json():
    with pytest.raises(MCPVideoError) as exc:
        parse_package_manifest("{this is not json")
    assert exc.value.code == "invalid_manifest_json"


def test_pkg_parse_rejects_invalid_utf8():
    with pytest.raises(MCPVideoError) as exc:
        parse_package_manifest(b"\xff\xfe\xfd")
    assert exc.value.code == "invalid_manifest_encoding"


def test_pkg_parse_rejects_non_object_payload():
    with pytest.raises(ValidationError):
        parse_package_manifest("[]")
    with pytest.raises(ValidationError):
        parse_package_manifest('"plain string"')
