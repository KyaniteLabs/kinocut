"""Lineage-bound, guarded salvage derivatives (Wave 3 Task 3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kinocut.aivideo.protection import MutationOperation, protect, touched_dependencies
from kinocut.aivideo.salvage import (
    SalvageRecipe,
    _mutation_intent,
    create_salvage_derivative,
)
from kinocut.aivideo.salvage_checks import _decoded_frame_hashes
from kinocut.aivideo.salvage_lineage import install_manifest
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.protection import ProtectedElement
from kinocut.contracts.review import ReviewDecision
from kinocut.engine_body_swap import _audio_fingerprint
from kinocut.engine_probe import probe
from kinocut.errors import MCPVideoError
from kinocut.projectstore import Project, append_record, ingest_asset, open_project, read_records
from tests.contracts_fixtures import protection_kwargs, review_decision_kwargs

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


def test_clean_edges_collides_with_protected_audio(source):
    project, original, source_path = source
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                element_type="audio_stream",
                dependency_fingerprint=_audio_fingerprint(str(source_path)),
            )
        ),
    )

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="clean_edges",
            policy={"trim_start": 0.2, "trim_end": 0.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )

    assert excinfo.value.code == "protected_element_change"


def test_source_replacement_during_snapshot_fails_before_render(source, monkeypatch):
    import kinocut.aivideo.salvage as salvage

    project, original, _source_path = source
    original_snapshot = salvage.copy_verified_snapshot

    def replace_then_snapshot(source_path_arg, destination, expected):
        Path(source_path_arg).write_bytes(b"substituted after authorization")
        return original_snapshot(source_path_arg, destination, expected)

    monkeypatch.setattr(salvage, "copy_verified_snapshot", replace_then_snapshot)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="clean_edges",
            policy={"trim_start": 0.2, "trim_end": 0.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )

    assert excinfo.value.code == "source_identity_changed"


def test_verified_source_cannot_be_substituted_and_restored_during_render(source, sample_video_no_audio, monkeypatch):
    import kinocut.aivideo.salvage as salvage

    project, original, _source_path = source
    original_render = salvage._render
    substitute = Path(sample_video_no_audio).read_bytes()

    def substitute_then_restore(recipe, policy, source_path, output, **kwargs):
        approved = Path(source_path).read_bytes()
        Path(source_path).write_bytes(substitute)
        try:
            original_render(recipe, policy, source_path, output, **kwargs)
        finally:
            Path(source_path).write_bytes(approved)

    monkeypatch.setattr(salvage, "_render", substitute_then_restore)

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="still_frame",
            policy={"timestamp": 1.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )

    assert excinfo.value.code == "invalid_record"
    assert len(read_records(project, "asset_record")) == 1


def test_clean_edges_rejects_same_duration_from_wrong_source_interval(source, monkeypatch):
    import kinocut.aivideo.salvage as salvage
    import kinocut.aivideo.salvage_render as salvage_render

    project, original, _source_path = source

    def wrong_interval(recipe, policy, source_path, output, **kwargs):
        duration = (
            salvage._probe_source(source_path, pass_fds=kwargs.get("pass_fds", ())).duration
            - policy["trim_start"]
            - policy["trim_end"]
        )
        salvage_render._trim_source(
            source_path,
            output,
            start=0.0,
            duration=duration,
            pass_fds=kwargs.get("pass_fds", ()),
        )

    monkeypatch.setattr(salvage, "_render", wrong_interval)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="clean_edges",
            policy={"trim_start": 0.5, "trim_end": 0.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )

    assert excinfo.value.code == "salvage_verification_failed"


def test_clean_edges_rejects_systematic_trim_interval_defect(source, monkeypatch):
    import kinocut.aivideo.salvage_render as salvage_render

    project, original, _source_path = source
    real_trim = salvage_render._trim_source

    def defective_trim(source_path, output, *, start, duration, pass_fds):
        real_trim(
            source_path,
            output,
            start=0.0,
            duration=duration,
            pass_fds=pass_fds,
        )

    monkeypatch.setattr(salvage_render, "_trim_source", defective_trim)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="clean_edges",
            policy={"trim_start": 0.5, "trim_end": 0.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )

    assert excinfo.value.code == "salvage_verification_failed"


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
    project, original, source_path = source
    intent = _mutation_intent(
        SalvageRecipe(recipe),
        policy,
        original.asset_id,
        _audio_fingerprint(str(source_path)),
        (),
    )
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

    def black_pad(_recipe, _policy, source_path, output_path, *, pass_fds=()):
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
            ],
            pass_fds=pass_fds,
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
    from kinocut.aivideo.salvage_render import _probe_source
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def sample_aware_forgery(_recipe, policy, source_path, output_path, *, pass_fds=()):
        source_info = _probe_source(source_path, pass_fds=pass_fds)
        frame_count = len(_decoded_frame_hashes(source_path, pass_fds=pass_fds))
        transition = frame_count - 1
        fps = source_info.fps
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
                str(source_info.duration + policy["extension_seconds"]),
                "-an",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            pass_fds=pass_fds,
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

    def wrong_origin(_recipe, _policy, source_path, output_path, *, pass_fds=()):
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
            ],
            pass_fds=pass_fds,
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


def test_freeze_rejects_forgery_that_substitutes_prefix_frames(source, monkeypatch):
    """Reject a freeze render whose pre-transition frames were substituted."""
    from kinocut.aivideo.salvage_render import _probe_source
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def prefix_substitution(_recipe, policy, source_path, output_path, *, pass_fds=()):
        source_info = _probe_source(source_path, pass_fds=pass_fds)
        transition = len(_decoded_frame_hashes(source_path, pass_fds=pass_fds)) - 1
        # Black out frames BEFORE the transition so the tail + extension still
        # match the source tail, defeating checks that only sample the suffix.
        filters = (
            f"drawbox=color=black:t=fill:enable='lt(n\\,{transition})',"
            f"tpad=stop_mode=clone:stop_duration={policy['extension_seconds']}"
        )
        _run_ffmpeg(
            [
                "-i",
                str(source_path),
                "-vf",
                filters,
                "-t",
                str(source_info.duration + policy["extension_seconds"]),
                "-an",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", prefix_substitution)
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


def test_region_crop_rejects_same_dimensions_from_wrong_origin(source, monkeypatch):
    """Reject a region_crop with the requested dimensions but the wrong offset."""
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def wrong_offset(_recipe, _policy, source_path, output_path, *, pass_fds=()):
        # Declared region is x=0.25,y=0.25 -> pixel offset (160,120). Render
        # from (0,0) instead so dimensions match but content does not.
        _run_ffmpeg(
            [
                "-i",
                str(source_path),
                "-vf",
                "crop=320:240:0:0",
                "-c:a",
                "copy",
                str(output_path),
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", wrong_offset)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="region_crop",
            policy={"region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
        )
    assert excinfo.value.code == "salvage_verification_failed"
    assert excinfo.value.error_type == "processing_error"


def test_still_frame_rejects_render_unbound_to_declared_timestamp(source, monkeypatch):
    """Reject a still_frame whose pixels do not match the declared timestamp."""
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    project, original, _source_path = source

    def synthetic_still(_recipe, _policy, _source_path, output_path, *, pass_fds=()):
        # Produce a solid red frame that no source timestamp would yield.
        _run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=red:size=640x480:d=0.1",
                "-frames:v",
                "1",
                str(output_path),
            ],
            pass_fds=pass_fds,
        )

    monkeypatch.setattr("kinocut.aivideo.salvage._render", synthetic_still)
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="still_frame",
            policy={"timestamp": 1.0},
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


# ---------------------------------------------------------------------------
# §1.1 salvage lineage schema v2: persisted mutation_fingerprint and
# authorization_decision_ids; tamper/forgery/replay fail closed; idempotent
# re-runs and safe v1 backward behavior.
# ---------------------------------------------------------------------------


def _repoint_asset_artifact(project: Project, asset: AssetRecord, new_artifact_id: str) -> AssetRecord:
    """Supersede one asset record to point at a different lineage artifact."""

    repointed = asset.model_copy(
        update={
            "record_id": None,
            "supersedes": asset.record_id,
            "derived_artifact_ids": (new_artifact_id,),
        }
    )
    return append_record(project, repointed)


def _install_custom_manifest(project: Project, payload: dict) -> tuple[str, str]:
    """Install an arbitrary manifest payload via the canonical installer."""

    return install_manifest(project, payload)


def _v1_payload_from_v2(payload: dict) -> dict:
    """Strip v2-only fields to produce a legacy v1-shaped manifest."""

    v1 = dict(payload)
    v1.pop("mutation_fingerprint", None)
    v1.pop("authorization_decision_ids", None)
    v1["schema_version"] = 1
    return v1


def test_salvage_manifest_persists_v2_schema_with_fingerprint_and_authorization_refs(source):
    """v2 manifest records the exact mutation_fingerprint and auth refs."""

    project, original, source_path = source
    audio_fingerprint = _audio_fingerprint(str(source_path))
    auth_a = "sha256:" + "b" * 64
    auth_b = "sha256:" + "c" * 64

    result = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
        authorization_decision_ids=(auth_a, auth_b),
    )

    manifest = json.loads((project.root / result.lineage_artifact_location).read_text())
    assert manifest["schema_version"] == 2
    expected_intent = _mutation_intent(
        SalvageRecipe.STILL_FRAME,
        result.policy,
        original.asset_id,
        audio_fingerprint,
        (auth_a, auth_b),
    )
    from kinocut.aivideo.protection import mutation_fingerprint

    assert manifest["mutation_fingerprint"] == mutation_fingerprint(expected_intent)
    assert manifest["authorization_decision_ids"] == [auth_a, auth_b]
    assert str(project.root) not in json.dumps(manifest)


def test_idempotent_replay_reuses_v2_manifest_without_re_rendering(source):
    """A second call reads the same v2 derivative without rendering again."""

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
    assert second.lineage_artifact_id == first.lineage_artifact_id
    assert len(read_records(project, "clip_verdict")) == 1


def test_v2_manifest_with_tampered_fingerprint_fails_closed(source):
    """Replay fails when the stored mutation_fingerprint disagrees with recompute."""

    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    first = create_salvage_derivative(project, **kwargs)

    manifest_path = project.root / first.lineage_artifact_location
    payload = json.loads(manifest_path.read_text())
    payload["mutation_fingerprint"] = "sha256:" + "0" * 64
    tampered_id, _ = _install_custom_manifest(project, payload)
    _repoint_asset_artifact(project, first.asset, tampered_id)

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "salvage_integrity_failed"
    assert excinfo.value.error_type == "integrity_error"


def test_v2_manifest_with_tampered_authorization_ref_fails_closed(source):
    """Replay fails when a stored authorization_decision_id is not a valid approval."""

    project, original, _source_path = source
    forged_ref = "sha256:" + "9" * 64
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
        authorization_decision_ids=(forged_ref,),
    )
    first = create_salvage_derivative(project, **kwargs)

    manifest_path = project.root / first.lineage_artifact_location
    payload = json.loads(manifest_path.read_text())
    payload["authorization_decision_ids"] = ["sha256:" + "5" * 64]
    tampered_id, _ = _install_custom_manifest(project, payload)
    _repoint_asset_artifact(project, first.asset, tampered_id)

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "salvage_integrity_failed"


def test_stale_authorization_ref_fails_closed_after_supersession(source):
    """Replay fails when a stored authorization_decision_id has been superseded."""

    project, original, source_path = source
    audio_fingerprint = _audio_fingerprint(str(source_path))
    intent = _mutation_intent(
        SalvageRecipe.STILL_FRAME,
        {"recipe": "still_frame", "timestamp": 1.0},
        original.asset_id,
        audio_fingerprint,
        (),
    )
    from kinocut.aivideo.protection import mutation_fingerprint

    intent_fingerprint = mutation_fingerprint(intent)
    approval = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=intent_fingerprint,
                dependency_fingerprint=intent_fingerprint,
            )
        ),
    )
    result = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
        authorization_decision_ids=(approval.record_id,),
    )
    assert result.asset.record_id is not None

    # Supersede the stored approval: replay must fail because the ref is no
    # longer active and human-bound to the fingerprint.
    superseding = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=intent_fingerprint,
                dependency_fingerprint=intent_fingerprint,
                supersedes=approval.record_id,
            )
        ),
    )
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(
            project,
            source_asset_id=original.asset_id,
            recipe="still_frame",
            policy={"timestamp": 1.0},
            acceptance_spec_id=_ACCEPTANCE_SPEC,
            authorization_decision_ids=(superseding.record_id,),
        )
    assert excinfo.value.code == "salvage_integrity_failed"


def test_new_protected_lock_blocks_idempotent_replay(source):
    """A protected element added after render blocks replay (fresh approval needed)."""

    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    create_salvage_derivative(project, **kwargs)

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
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "protected_element_change"


def test_v1_manifest_replay_succeeds_without_protection(source):
    """A legacy v1 manifest remains idempotent when no protection applies."""

    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    first = create_salvage_derivative(project, **kwargs)

    manifest_path = project.root / first.lineage_artifact_location
    v2_payload = json.loads(manifest_path.read_text())
    v1_payload = _v1_payload_from_v2(v2_payload)
    v1_id, _ = _install_custom_manifest(project, v1_payload)
    _repoint_asset_artifact(project, first.asset, v1_id)

    replayed = create_salvage_derivative(project, **kwargs)
    assert replayed.lineage_artifact_id == v1_id
    assert replayed.asset.derived_artifact_ids == (v1_id,)


def test_v1_manifest_cannot_bypass_current_protected_lock(source):
    """A legacy v1 manifest cannot bypass a protected element added later."""

    project, original, _source_path = source
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    first = create_salvage_derivative(project, **kwargs)

    manifest_path = project.root / first.lineage_artifact_location
    v2_payload = json.loads(manifest_path.read_text())
    v1_payload = _v1_payload_from_v2(v2_payload)
    v1_id, _ = _install_custom_manifest(project, v1_payload)
    _repoint_asset_artifact(project, first.asset, v1_id)

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
    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "protected_element_change"


def test_v2_manifest_replay_succeeds_through_fresh_protected_lock(source):
    """Replay succeeds when a stored v2 auth ref clears a current protected lock."""

    project, original, source_path = source
    audio_fingerprint = _audio_fingerprint(str(source_path))

    # Lock the source asset with an original human approval.
    original_approval = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=original.asset_id,
                dependency_fingerprint=original.asset_id,
            )
        ),
    )
    protect(
        project,
        ProtectedElement(
            **protection_kwargs(
                project_id=project.project_id,
                dependency_fingerprint=original.asset_id,
                element_type="source_asset",
                human_approval_ref=original_approval.record_id,
            )
        ),
    )

    # Build the salvage intent fingerprint and issue a fresh human approval
    # that derives from the lock and the original approval.
    intent = _mutation_intent(
        SalvageRecipe.STILL_FRAME,
        {"recipe": "still_frame", "timestamp": 1.0},
        original.asset_id,
        audio_fingerprint,
        (),
    )
    from kinocut.aivideo.protection import mutation_fingerprint

    intent_fingerprint = mutation_fingerprint(intent)
    salvage_approval = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=intent_fingerprint,
                dependency_fingerprint=intent_fingerprint,
                source_record_ids=(original_approval.record_id,),
            )
        ),
    )

    first = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
        authorization_decision_ids=(salvage_approval.record_id,),
    )
    second = create_salvage_derivative(
        project,
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
        authorization_decision_ids=(salvage_approval.record_id,),
    )
    assert second.asset.record_id == first.asset.record_id
    assert second.lineage_artifact_id == first.lineage_artifact_id


# ---------------------------------------------------------------------------
# Authorization-ref resolver unification: hostile target_ref mismatch must fail
# closed; the shared resolver rejects subclass lookalikes, stale/superseded
# decisions, and decisions whose target_ref disagrees with the fingerprint.
# ---------------------------------------------------------------------------


def test_v2_manifest_replay_rejects_authorization_ref_with_hostile_target_ref(source):
    """A stored auth ref with correct dependency_fingerprint but hostile target_ref fails."""

    project, original, source_path = source
    audio_fingerprint = _audio_fingerprint(str(source_path))
    kwargs = dict(
        source_asset_id=original.asset_id,
        recipe="still_frame",
        policy={"timestamp": 1.0},
        acceptance_spec_id=_ACCEPTANCE_SPEC,
    )
    first = create_salvage_derivative(project, **kwargs)

    intent = _mutation_intent(
        SalvageRecipe.STILL_FRAME,
        {"recipe": "still_frame", "timestamp": 1.0},
        original.asset_id,
        audio_fingerprint,
        (),
    )
    from kinocut.aivideo.protection import mutation_fingerprint

    intent_fingerprint = mutation_fingerprint(intent)

    # Hostile: correct dependency_fingerprint but WRONG target_ref.
    hostile = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref="sha256:" + "e" * 64,
                dependency_fingerprint=intent_fingerprint,
            )
        ),
    )

    manifest_path = project.root / first.lineage_artifact_location
    payload = json.loads(manifest_path.read_text())
    payload["authorization_decision_ids"] = [hostile.record_id]
    tampered_id, _ = _install_custom_manifest(project, payload)
    _repoint_asset_artifact(project, first.asset, tampered_id)

    with pytest.raises(MCPVideoError) as excinfo:
        create_salvage_derivative(project, **kwargs)
    assert excinfo.value.code == "salvage_integrity_failed"
    assert excinfo.value.error_type == "integrity_error"
