"""JSON-in/JSON-out façade for fake remote contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .adapters import (
    FakeDeliveryAdapter,
    FakeHostingAdapter,
    FakeRenderAdapter,
    prepare_remote_job,
)
from .contracts import EgressManifest, Money, NetworkApproval, RemoteContractError
from .jobs import (
    AdapterKind,
    ApprovedLocalPlan,
    DeletionRecord,
    DownloadedArtifact,
    LocalArtifactVerification,
    RemoteExecutionSelection,
    RemoteJobReceipt,
    RemoteJobSpec,
    promote_downloaded_artifact,
)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _selection(
    manifest: EgressManifest,
    *,
    kind: AdapterKind,
    selected_by: str,
    selected_at: str,
) -> RemoteExecutionSelection:
    return RemoteExecutionSelection.create(
        provider=manifest.location.provider,
        kind=kind,
        selected_by=selected_by,
        selected_at=_parse_time(selected_at),
    )


def _map_with_adapter(
    local_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    network_approval: Mapping[str, Any],
    *,
    adapter_kind: AdapterKind,
    selected_by: str,
    selected_at: str,
    destination: str | None = None,
) -> dict[str, Any]:
    parsed_manifest = EgressManifest.model_validate(manifest)
    if adapter_kind == "render":
        if destination is not None:
            raise RemoteContractError("render adapter does not accept a delivery destination")
        adapter = FakeRenderAdapter(provider=parsed_manifest.location.provider)
    elif adapter_kind == "delivery":
        if destination is None:
            raise RemoteContractError("delivery destination is required")
        adapter = FakeDeliveryAdapter(provider=parsed_manifest.location.provider, destination=destination)
    elif adapter_kind == "hosting":
        if destination is None:
            raise RemoteContractError("hosting destination is required")
        adapter = FakeHostingAdapter(provider=parsed_manifest.location.provider, destination=destination)
    else:
        raise RemoteContractError(f"unknown adapter kind: {adapter_kind}")
    job = prepare_remote_job(
        adapter=adapter,
        local_plan=ApprovedLocalPlan.model_validate(local_plan),
        manifest=parsed_manifest,
        network_approval=NetworkApproval.model_validate(network_approval),
        selection=_selection(
            parsed_manifest,
            kind=adapter_kind,
            selected_by=selected_by,
            selected_at=selected_at,
        ),
    )
    return job.model_dump(mode="json")


def map_fake_remote_job(
    local_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    network_approval: Mapping[str, Any],
    *,
    adapter_kind: AdapterKind,
    selected_by: str,
    selected_at: str,
) -> dict[str, Any]:
    """Map an approved plan with a deterministic fake provider adapter."""

    return _map_with_adapter(
        local_plan,
        manifest,
        network_approval,
        adapter_kind=adapter_kind,
        selected_by=selected_by,
        selected_at=selected_at,
    )


def plan_delivery(
    local_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    network_approval: Mapping[str, Any],
    *,
    destination: str,
    selected_by: str,
    selected_at: str,
) -> dict[str, Any]:
    """Plan an explicit fake delivery job without performing network I/O."""

    return _map_with_adapter(
        local_plan,
        manifest,
        network_approval,
        adapter_kind="delivery",
        selected_by=selected_by,
        selected_at=selected_at,
        destination=destination,
    )


def plan_hosting(
    local_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    network_approval: Mapping[str, Any],
    *,
    destination: str,
    selected_by: str,
    selected_at: str,
) -> dict[str, Any]:
    """Plan an explicit fake hosting job without performing network I/O."""

    return _map_with_adapter(
        local_plan,
        manifest,
        network_approval,
        adapter_kind="hosting",
        selected_by=selected_by,
        selected_at=selected_at,
        destination=destination,
    )


def create_fake_remote_receipt(
    job: Mapping[str, Any],
    *,
    provider_job_version: str,
    actual_cost: Mapping[str, Any],
    retries: int,
    downloads: list[dict[str, Any]],
    deletion: Mapping[str, Any],
    provider_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic fake provider receipt from JSON-compatible values."""

    parsed_job = RemoteJobSpec.model_validate(job)
    receipt = RemoteJobReceipt.create(
        job=parsed_job,
        provider_job_id="fake-job-" + parsed_job.job_sha256.removeprefix("sha256:")[:16],
        provider_job_version=provider_job_version,
        status="completed",
        actual_cost=Money.model_validate(actual_cost),
        retries=retries,
        downloads=tuple(DownloadedArtifact.model_validate(item) for item in downloads),
        deletion=DeletionRecord.model_validate(deletion),
        provider_metadata=provider_metadata,
    )
    return receipt.model_dump(mode="json")


def verify_local_promotion(
    download: Mapping[str, Any],
    local_verification: Mapping[str, Any],
    *,
    destination: str,
) -> dict[str, Any]:
    """Validate a local receipt before returning a pure promotion authorization."""

    promotion = promote_downloaded_artifact(
        DownloadedArtifact.model_validate(download),
        LocalArtifactVerification.model_validate(local_verification),
        destination=destination,
    )
    return promotion.model_dump(mode="json")
