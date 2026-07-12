"""Lineage-bound, guarded salvage derivatives (Wave 3 Task 3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kinocut.aivideo.protection import MutationOperation, protect, touched_dependencies
from kinocut.aivideo.salvage import (
    SalvageRecipe,
    _decoded_frame_hashes,
    _mutation_intent,
    create_salvage_derivative,
)
from kinocut.contracts.protection import ProtectedElement
from kinocut.engine_probe import probe
from kinocut.errors import MCPVideoError
from kinocut.projectstore import ingest_asset, open_project, read_records
from tests.contracts_fixtures import protection_kwargs

_ACCEPTANCE_SPEC = "sha256:" + "a" * 64


def _sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    asset = ingest_asset(project, sample_video)
    stored = project.root / asset.original_location
    return project, asset, stored


_RECIPES = (
    (SalvageRecipe.CLEAN_EDGES, {"trim_start": 0.2, "trim_end": 0.3}),
    (SalvageRecipe.FREEZE_EXTENSION, {"extension_seconds": 0.4}),
    (SalvageRecipe.STILL_FRAME, {"timestamp": 1.0}),
    (
        SalvageRecipe.REGION_CROP,
        {"region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}},
    ),
    (
        SalvageRecipe.BACKGROUND_ONLY,
        {"region": {"x": 0.0, "y": 0.5, "width": 1.0, "height": 0.5}},
    ),
)


@pytest.mark.parametrize(("recipe", "policy"), _RECIPES)
def test_each_recipe_creates_guarded_lineage_and_unapproved_verdict(source, recipe, policy):
    project, original, source_path = source
    before = _sha(source_path)

    result = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe=recipe,
        policy=policy,
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )

    output = project.root / result.asset.original_location
    assert output.is_file()
    assert output != source_path
    assert _sha(source_path) == before == original.asset_id
    assert _sha(output) == result.output_hash == result.asset.asset_id
    assert result.asset.parent_asset_id == original.asset_id
    assert result.asset.variant_of == original.asset_id
    assert result.asset.lineage.source_asset_ids == (original.asset_id,)
    assert result.asset.lineage.generation_settings_hash == result.policy_hash
    assert result.recipe is recipe
    assert result.policy["recipe"] == recipe.value
    assert result.lineage_artifact_id in result.asset.derived_artifact_ids
    assert result.verdict.asset_hash == result.output_hash
    assert result.verdict.disposition.value == "repairable"
    assert result.verdict.review_decision_id is None
    assert result.verdict.created_by == "tool:salvage"
    assert all(check.passed for check in result.preservation_checks)

    manifest = project.root / result.lineage_artifact_location
    assert manifest.is_file()
    assert _sha(manifest) == result.lineage_artifact_id
    assert str(project.root) not in manifest.read_text(encoding="utf-8")


def test_real_media_properties_match_recipe_claims(source):
    project, original, source_path = source
    source_info = probe(str(source_path))

    trimmed = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="clean_edges",
        policy={"trim_start": 0.2, "trim_end": 0.3},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    frozen = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="freeze_extension",
        policy={"extension_seconds": 0.4},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    cropped = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="region_crop",
        policy={"region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    background = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="background_only",
        policy={"region": {"x": 0.0, "y": 0.5, "width": 1.0, "height": 0.5}},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )

    assert probe(str(project.root / trimmed.asset.original_location)).duration == pytest.approx(
        source_info.duration - 0.5, abs=0.12
    )
    assert probe(str(project.root / frozen.asset.original_location)).duration == pytest.approx(
        source_info.duration + 0.4, abs=0.12
    )
    crop_info = probe(str(project.root / cropped.asset.original_location))
    assert (crop_info.width, crop_info.height) == (320, 240)
    background_info = probe(str(project.root / background.asset.original_location))
    assert (background_info.width, background_info.height) == (640, 240)
    assert background_info.audio_codec is None
    background_manifest = (project.root / background.lineage_artifact_location).read_text(encoding="utf-8")
    assert '"region":{"height":0.5,"width":1.0,"x":0.0,"y":0.5}' in background_manifest
    assert not any(word in background_manifest for word in ("inpaint", "remove_subject", "semantic_removal"))


def test_same_operation_is_idempotent_and_tamper_fails_closed(source):
    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    first = create_salvage_derivative(project, **kwargs)
    second = create_salvage_derivative(project, **kwargs)
    assert second.asset.record_id == first.asset.record_id
    assert second.verdict.record_id == first.verdict.record_id
    assert len(read_records(project, "clip_verdict")) == 1

    (project.root / first.asset.original_location).write_bytes(b"tampered")
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "salvage_integrity_failed"
    assert excinfo.value.error_type == "integrity_error"


@pytest.mark.parametrize("missing", ["output", "manifest"])
def test_missing_previously_published_artifact_fails_without_recreation(source, missing):
    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    result = create_salvage_derivative(project, **kwargs)
    target = project.root / (
        result.asset.original_location if missing == "output" else result.lineage_artifact_location
    )
    target.unlink()

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)

    assert excinfo.value.code == "salvage_integrity_failed"
    assert excinfo.value.error_type == "integrity_error"
    assert not target.exists()


_PROTECTION_CASES = [
    ("clean_edges", {"trim_start": 0.1, "trim_end": 0.1}, "salvage_clean_edges"),
    ("freeze_extension", {"extension_seconds": 0.2}, "salvage_freeze_extension"),
    ("still_frame", {"timestamp": 1.0}, "salvage_still_frame"),
    (
        "region_crop",
        {"region": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}},
        "salvage_region_crop",
    ),
    (
        "background_only",
        {"region": {"x": 0.0, "y": 0.5, "width": 1.0, "height": 0.5}},
        "salvage_background_only",
    ),
]


@pytest.mark.parametrize(("recipe", "policy", "operation"), _PROTECTION_CASES)
def test_each_recipe_has_closed_footprint_and_protection_gate(source, monkeypatch, recipe, policy, operation):
    project, original, _source_path = source
    intent = _mutation_intent(SalvageRecipe(recipe), policy, original.asset_id, ())
    assert intent.operation is MutationOperation(operation)
    assert ("source_asset", original.asset_id) in {
        (kind.value, fingerprint) for kind, fingerprint in touched_dependencies(intent)
    }
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                dependency_fingerprint=original.asset_id,
                element_type="source_asset",
            )
        ),
    )
    rendered = False

    def should_not_render(*args, **kwargs):
        nonlocal rendered
        rendered = True
        raise AssertionError("render must not run")

    monkeypatch.setattr("kinocut.aivideo.salvage._render", should_not_render)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe=recipe,
            policy=policy,
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "protected_element_change"
    assert rendered is False


@pytest.mark.parametrize(("recipe", "policy", "operation"), _PROTECTION_CASES)
def test_each_recipe_honors_exact_allowed_operation(source, monkeypatch, recipe, policy, operation):
    project, original, _source_path = source
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                dependency_fingerprint=original.asset_id,
                element_type="source_asset",
                allowed_operations=(operation,),
            )
        ),
    )

    class RenderReached(Exception):
        pass

    def reached(*args, **kwargs):
        raise RenderReached

    monkeypatch.setattr("kinocut.aivideo.salvage._render", reached)
    with pytest.raises(RenderReached):
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe=recipe,
            policy=policy,
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )


def test_freeze_proof_binds_source_tail_and_every_extension_sample(source):
    project, original, _source_path = source
    result = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="freeze_extension",
        policy={"extension_seconds": 0.4},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    checks = {check.claim: check for check in result.preservation_checks}
    assert checks["freeze_source_tail_match"].passed
    assert checks["freeze_extension_frames_identical"].passed
    assert checks["audio_removed"].passed
    assert checks["freeze_extension_frames_identical"].expected.startswith("md5:")


def test_black_padding_cannot_pass_as_freeze(source, monkeypatch):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def black_pad(_recipe, _policy, source_path, output_path):
        _run_ffmpeg(
            [
                "-i",
                str(source_path),
                "-vf",
                "tpad=stop_mode=add:color=black:stop_duration=0.4",
                "-t",
                "3.4",
                "-an",
                str(output_path),
            ]
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", black_pad)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="freeze_extension",
            policy={"extension_seconds": 0.4},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "salvage_verification_failed"
    assert excinfo.value.error_type == "processing_error"


def test_freeze_rejects_forgery_that_only_matches_old_sample_indexes(source, monkeypatch):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def sample_aware_forgery(_recipe, policy, source_path, output_path):
        frame_count = len(_decoded_frame_hashes(source_path))
        transition = frame_count - 1
        fps = probe(str(source_path)).fps
        samples = {
            transition + max(1, round(policy["extension_seconds"] * fps * fraction)) for fraction in (0.2, 0.5, 0.8)
        }
        exclusions = "+".join(f"eq(n\\,{index})" for index in sorted(samples))
        bad_extension = f"gte(n\\,{transition + 1})*not({exclusions})"
        filters = (
            f"tpad=stop_mode=clone:stop_duration={policy['extension_seconds']},"
            f"drawbox=color=black:t=fill:enable='{bad_extension}*not(mod(n\\,2))',"
            f"drawbox=color=white:t=fill:enable='{bad_extension}*mod(n\\,2)'"
        )
        _run_ffmpeg(
            [
                "-i",
                str(source_path),
                "-vf",
                filters,
                "-t",
                str(probe(str(source_path)).duration + policy["extension_seconds"]),
                "-an",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", sample_aware_forgery)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="freeze_extension",
            policy={"extension_seconds": 0.4},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "salvage_verification_failed"
    assert excinfo.value.error_type == "processing_error"


def test_background_rejects_same_dimensions_from_wrong_origin(source, monkeypatch):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def wrong_origin(_recipe, _policy, source_path, output_path):
        _run_ffmpeg(
            [
                "-i",
                str(source_path),
                "-vf",
                "crop=640:240:0:0",
                "-an",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", wrong_origin)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="background_only",
            policy={"region": {"x": 0.0, "y": 0.5, "width": 1.0, "height": 0.5}},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "salvage_verification_failed"
    assert excinfo.value.error_type == "processing_error"


@pytest.mark.parametrize(
    "recipe,policy",
    [
        ("clean_edges", {"trim_start": -1, "trim_end": 0}),
        ("clean_edges", {"trim_start": 0, "trim_end": 0}),
        ("freeze_extension", {"extension_seconds": 0}),
        ("still_frame", {"timestamp": -1}),
        ("region_crop", {"region": {"x": 0, "y": 0, "width": 2, "height": 1}}),
        ("region_crop", {"region": {"x": 0, "y": 0, "width": 1, "height": 1}}),
        ("background_only", {}),
        ("background_only", {"force": True}),
    ],
)
def test_invalid_or_bypass_policy_fails_closed(source, recipe, policy):
    project, original, _source_path = source
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe=recipe,
            policy=policy,
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "invalid_salvage_policy"
