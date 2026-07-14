from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mcp_video.remote import (
    EgressFile,
    EgressManifest,
    Money,
    NetworkApproval,
    ProviderLocation,
    RetentionPolicy,
    approve_egress,
    assert_network_approval,
    plan_egress,
    validate_egress_approval,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
APPROVED_AT = datetime(2026, 7, 9, 20, 0, tzinfo=UTC)


def _manifest(*, provider: str = "fake-render") -> EgressManifest:
    return EgressManifest.create(
        files=(
            EgressFile(
                path="inputs/z-source.mp4",
                sha256=HASH_B,
                size_bytes=22,
                media_type="video/mp4",
                metadata={"role": "source"},
            ),
            EgressFile(
                path="plans/approved.json",
                sha256=HASH_A,
                size_bytes=11,
                media_type="application/json",
                metadata={"role": "approved_plan"},
            ),
        ),
        metadata={"project_id": "project-7", "purpose": "explicit remote render"},
        location=ProviderLocation(provider=provider, region_known=True, region="us-west-2"),
        retention=RetentionPolicy(mode="delete_after_download", maximum_days=1),
        estimated_cost=Money(amount=Decimal("1.25"), currency="USD"),
    )


def test_egress_manifest_is_exact_canonical_and_hash_bound() -> None:
    first = _manifest()
    second = _manifest()

    assert tuple(item.path for item in first.files) == (
        "inputs/z-source.mp4",
        "plans/approved.json",
    )
    assert first.location == ProviderLocation(provider="fake-render", region_known=True, region="us-west-2")
    assert first.retention == RetentionPolicy(mode="delete_after_download", maximum_days=1)
    assert first.estimated_cost == Money(amount=Decimal("1.25"), currency="USD")
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_sha256.startswith("sha256:")


def test_manifest_requires_relative_unique_files_and_an_explicit_region_state() -> None:
    with pytest.raises(ValueError, match="relative path"):
        EgressFile(
            path="/private/source.mp4",
            sha256=HASH_A,
            size_bytes=1,
            media_type="video/mp4",
        )

    with pytest.raises(ValueError, match="region is required"):
        ProviderLocation(provider="fake-render", region_known=True, region=None)

    with pytest.raises(ValueError, match="region must be omitted"):
        ProviderLocation(provider="fake-render", region_known=False, region="us-west-2")

    source = EgressFile(
        path="inputs/source.mp4",
        sha256=HASH_A,
        size_bytes=1,
        media_type="video/mp4",
    )
    with pytest.raises(ValueError, match="unique"):
        EgressManifest.create(
            files=(source, source),
            metadata={},
            location=ProviderLocation(provider="fake-render", region_known=False),
            retention=RetentionPolicy(mode="provider_default"),
            estimated_cost=Money(amount=Decimal("0"), currency="USD"),
        )


def test_network_approval_is_separate_and_bound_to_the_exact_manifest() -> None:
    manifest = _manifest()
    approval = NetworkApproval.create(
        manifest=manifest,
        approved_by="operator",
        approved_at=APPROVED_AT,
    )

    assert approval.scope == "network_egress"
    assert approval.manifest_sha256 == manifest.manifest_sha256
    assert_network_approval(manifest, approval)

    other_manifest = _manifest(provider="fake-delivery")
    with pytest.raises(ValueError, match="does not match"):
        assert_network_approval(other_manifest, approval)


def test_credentials_are_redacted_from_every_manifest_metadata_level() -> None:
    secret = "sk-" + "x" * 32
    manifest = EgressManifest.create(
        files=(
            EgressFile(
                path="inputs/source.mp4",
                sha256=HASH_A,
                size_bytes=1,
                media_type="video/mp4",
                metadata={"authorization": "Bearer top-secret", "safe": "kept"},
            ),
        ),
        metadata={
            "nested": {"api_key": secret, "safe": ["visible", {"password": "hidden"}]},
            "token_shaped_value": secret,
        },
        location=ProviderLocation(provider="fake-render", region_known=False),
        retention=RetentionPolicy(mode="provider_default"),
        estimated_cost=Money(amount=Decimal("0"), currency="USD"),
    )

    serialized = manifest.model_dump_json()
    assert "top-secret" not in serialized
    assert secret not in serialized
    assert serialized.count("[REDACTED]") == 4
    assert manifest.files[0].metadata["safe"] == "kept"


def test_retention_contract_rejects_incoherent_maximum_days() -> None:
    with pytest.raises(ValueError, match="maximum_days is required"):
        RetentionPolicy(mode="fixed_days")

    with pytest.raises(ValueError, match="maximum_days must be omitted"):
        RetentionPolicy(mode="provider_default", maximum_days=30)


def test_egress_facade_accepts_and_returns_json_compatible_values() -> None:
    manifest = plan_egress(
        files=[
            {
                "path": "inputs/source.mp4",
                "sha256": HASH_A,
                "size_bytes": 1,
                "media_type": "video/mp4",
                "metadata": {"role": "source"},
            }
        ],
        metadata={"purpose": "explicit render"},
        provider="fake-render",
        region_known=True,
        region="us-west-2",
        retention={"mode": "delete_after_download", "maximum_days": 1},
        estimated_cost={"amount": "1.25", "currency": "USD"},
    )
    approval = approve_egress(
        manifest,
        approved_by="operator",
        approved_at="2026-07-09T20:00:00Z",
    )

    assert manifest["files"][0]["path"] == "inputs/source.mp4"
    assert manifest["estimated_cost"] == {"amount": "1.25", "currency": "USD"}
    assert approval["manifest_sha256"] == manifest["manifest_sha256"]
    assert validate_egress_approval(manifest, approval) is True
