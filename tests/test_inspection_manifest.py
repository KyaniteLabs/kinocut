"""InspectionPackage determinism, capability, and privacy contracts (Task 7)."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

from kinocut.aivideo.ingest import ingest_project_asset
from kinocut.aivideo.inspection.manifest import (
    ArtifactRef,
    InspectionPackage,
    ProviderCapabilityResult,
    persist_inspection_package,
)
from kinocut.aivideo.preflight import run_preflight
from kinocut.errors import MCPVideoError
from kinocut.projectstore import layout, open_project
from kinocut.projectstore import artifacts

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64


def _artifact(artifact_id: str, name: str, kind: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        location=str(layout.artifact_relative_path(artifact_id, name)),
    )


def test_artifact_layout_is_canonical_project_relative_and_content_addressed():
    assert layout.artifact_relative_path(_A, "motion strip.jpg") == PurePosixPath(
        ".kinocut", "artifacts", "sha256", "a" * 64, "motion_strip.jpg"
    )


def test_preflight_uses_the_shared_canonical_artifact_layout(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    asset = ingest_project_asset(project, sample_video)

    enriched = run_preflight(project, asset)

    expected = layout.artifact_relative_path(enriched.preflight_artifact_id, "preflight.json")
    assert (project.root / expected).is_file()


def test_inspection_package_explicitly_lists_unavailable_optional_analyzers():
    package = InspectionPackage(
        source_asset_id=_A,
        technical_metadata=_artifact(_A, "preflight.json", "technical_metadata"),
        capabilities=(
            ProviderCapabilityResult(
                capability_id="visual.motion_intent",
                available=False,
                reason_code="provider_not_configured",
            ),
            ProviderCapabilityResult(
                capability_id="visual.generative_defects",
                available=False,
                reason_code="provider_not_configured",
            ),
        ),
    )

    assert package.unavailable_capabilities == (
        "visual.motion_intent",
        "visual.generative_defects",
    )


def test_provider_capability_result_is_coherent_and_unique():
    with pytest.raises(ValidationError):
        ProviderCapabilityResult(
            capability_id="visual.motion_intent",
            available="false",
            reason_code="provider_not_configured",
        )
    with pytest.raises(ValidationError):
        ProviderCapabilityResult(
            capability_id="visual.motion_intent",
            available=True,
            reason_code="provider_not_configured",
        )
    capability = ProviderCapabilityResult(
        capability_id="visual.motion_intent",
        available=False,
        reason_code="provider_not_configured",
    )
    with pytest.raises(ValidationError):
        InspectionPackage(source_asset_id=_A, capabilities=(capability, capability))


def test_manifest_persistence_is_deterministic_and_privacy_safe(tmp_path):
    project = open_project(tmp_path / "private-project")
    package = InspectionPackage(
        source_asset_id=_A,
        technical_metadata=_artifact(_A, "preflight.json", "technical_metadata"),
        preview=_artifact(_B, "preview.mp4", "preview"),
        findings=(_B,),
        capabilities=(
            ProviderCapabilityResult(
                capability_id="visual.motion_intent",
                available=False,
                reason_code="provider_not_configured",
            ),
        ),
    )

    first = persist_inspection_package(project, package)
    second = persist_inspection_package(project, package)

    assert first == second
    assert not first.location.startswith("/")
    path = project.root / first.location
    raw = path.read_bytes()
    assert str(project.root).encode() not in raw
    assert b"/Users/" not in raw
    parsed = json.loads(raw)
    assert parsed["unavailable_capabilities"] == ["visual.motion_intent"]
    assert parsed["source_asset_id"] == _A


def test_artifact_ref_rejects_absolute_or_noncanonical_location():
    with pytest.raises(ValidationError):
        ArtifactRef(artifact_id=_A, kind="preview", location="/tmp/preview.mp4")
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id=_A,
            kind="preview",
            location=".kinocut/artifacts/sha256/" + "b" * 64 + "/preview.mp4",
        )


def test_manifest_read_failure_maps_to_a_private_custom_error(tmp_path, monkeypatch):
    project = open_project(tmp_path / "private-project")
    package = InspectionPackage(source_asset_id=_A)
    persist_inspection_package(project, package)

    def _unreadable(_path):
        raise OSError(f"secret host path: {tmp_path}")

    monkeypatch.setattr(Path, "read_bytes", _unreadable)
    with pytest.raises(MCPVideoError) as exc:
        persist_inspection_package(project, package)
    assert exc.value.code == "inspection_manifest_store_failed"
    assert str(tmp_path) not in str(exc.value)


def test_artifact_first_create_rolls_back_on_post_replace_fsync_failure(tmp_path, monkeypatch):
    project = open_project(tmp_path / "private-project")
    content = b"derived evidence"
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    target = project.root / layout.artifact_relative_path(artifact_id, "frame.jpg")
    real_fsync = artifacts.store._fsync_dir
    failed = False

    def _fail_once(directory):
        nonlocal failed
        if directory == target.parent and not failed:
            failed = True
            raise OSError(f"private fsync path: {tmp_path}")
        return real_fsync(directory)

    monkeypatch.setattr(artifacts.store, "_fsync_dir", _fail_once)
    with pytest.raises(MCPVideoError) as exc:
        artifacts.install_bytes(project, content, name="frame.jpg")

    assert exc.value.code == "artifact_store_failed"
    assert str(tmp_path) not in str(exc.value)
    assert not target.exists()
    assert not list(target.parent.glob(".*.tmp"))
    assert not list(target.parent.glob(".*.bak.*"))


def test_artifact_install_refuses_symlinked_destination(tmp_path):
    project = open_project(tmp_path / "private-project")
    content = b"derived evidence"
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    target = project.root / layout.artifact_relative_path(artifact_id, "frame.jpg")
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"DO NOT REPLACE")
    target.symlink_to(outside)

    with pytest.raises(MCPVideoError):
        artifacts.install_bytes(project, content, name="frame.jpg")

    assert outside.read_bytes() == b"DO NOT REPLACE"


def test_artifact_install_refuses_symlinked_digest_parent(tmp_path):
    project = open_project(tmp_path / "private-project")
    content = b"derived evidence"
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    relative = layout.artifact_relative_path(artifact_id, "frame.jpg")
    digest_parent = project.root / relative.parent
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    digest_parent.parent.mkdir(parents=True, exist_ok=True)
    digest_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MCPVideoError):
        artifacts.install_bytes(project, content, name="frame.jpg")

    assert list(outside.iterdir()) == []


def test_artifact_identity_mismatch_preserves_prior_bytes(tmp_path):
    project = open_project(tmp_path / "private-project")
    content = b"derived evidence"
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    target = project.root / layout.artifact_relative_path(artifact_id, "frame.jpg")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"HOSTILE PRIOR BYTES")

    with pytest.raises(MCPVideoError) as exc:
        artifacts.install_bytes(project, content, name="frame.jpg")

    assert exc.value.code == "artifact_identity_mismatch"
    assert target.read_bytes() == b"HOSTILE PRIOR BYTES"
