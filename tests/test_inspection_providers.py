"""Capability-gated optional visual findings providers (Wave 2 Task 9)."""

from __future__ import annotations

import json

import pytest

from kinocut.aivideo.inspection.manifest import ArtifactRef, InspectionPackage
from kinocut.aivideo.inspection.providers import (
    ProviderDefinition,
    ProviderFindingBatch,
    ProviderFindingProposal,
    ProviderRegistry,
    analyze_optional_visual_findings,
)
from kinocut.contracts.defect import DefectCode, DefectStatus, Severity
from kinocut.errors import MCPVideoError
from kinocut.projectstore import layout

_ASSET = "sha256:" + "a" * 64
_EVIDENCE_A = "sha256:" + "b" * 64
_EVIDENCE_B = "sha256:" + "c" * 64


def _artifact(artifact_id: str, name: str, kind: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        location=str(layout.artifact_relative_path(artifact_id, name)),
    )


def _package() -> InspectionPackage:
    return InspectionPackage(
        source_asset_id=_ASSET,
        preview=_artifact(_EVIDENCE_A, "preview.mp4", "preview"),
        frame_difference_measurements=(_artifact(_EVIDENCE_B, "frame_differences.json", "frame_differences"),),
    )


class _Provider:
    provider_id = "fixture_visual"
    capability_ids = ("visual.motion_intent", "visual.generative_defects")

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def analyze(self, package, capability_id):
        self.calls += 1
        assert package == _package()
        return self.payload


def _registry(provider: _Provider) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderDefinition(
                provider_id="fixture_visual",
                factory=lambda: provider,
            ),
        )
    )


def _proposal(**updates) -> ProviderFindingProposal:
    values = {
        "defect_code": DefectCode.WARPING,
        "time_range": (1.0, 2.0),
        "severity": Severity.HIGH,
        "confidence": 0.8,
        "evidence_artifact_ids": (_EVIDENCE_A,),
    }
    values.update(updates)
    return ProviderFindingProposal(**values)


def _batch(*proposals: ProviderFindingProposal) -> ProviderFindingBatch:
    return ProviderFindingBatch(
        provider_id="fixture_visual",
        capability_id="visual.generative_defects",
        findings=proposals,
    )


def test_absent_provider_is_typed_unavailable_and_does_not_mutate_package():
    package = _package()

    result = analyze_optional_visual_findings(
        package,
        playable_end=10.0,
        capability_id="visual.motion_intent",
        provider_id=None,
        project_id="project-7",
        created_by="agent:inspection",
    )

    assert result.status == "capability_unavailable"
    assert result.capability.available is False
    assert result.capability.reason_code == "provider_not_configured"
    assert result.playable_end == 10.0
    assert result.findings == ()
    assert package == _package()


def test_unknown_static_provider_fails_soft_without_loading_or_downloading():
    result = analyze_optional_visual_findings(
        _package(),
        playable_end=10.0,
        capability_id="visual.generative_defects",
        provider_id="not_installed",
        project_id="project-7",
        created_by="agent:inspection",
        registry=ProviderRegistry(),
    )

    assert result.status == "capability_unavailable"
    assert result.capability.reason_code == "provider_not_installed"
    assert result.provider_id == "not_installed"


def test_present_provider_normalizes_orders_and_keeps_findings_suspected():
    provider = _Provider(
        _batch(
            _proposal(time_range=(8.0, 9.0), defect_code=DefectCode.FLICKER),
            _proposal(time_range=(1.0, 2.0), defect_code=DefectCode.WARPING),
        )
    )

    result = analyze_optional_visual_findings(
        _package(),
        playable_end=10.0,
        capability_id="visual.generative_defects",
        provider_id="fixture_visual",
        project_id="project-7",
        created_by="agent:inspection",
        registry=_registry(provider),
    )

    assert result.status == "complete"
    assert result.capability.available is True
    assert [finding.time_range for finding in result.findings] == [(1.0, 2.0), (8.0, 9.0)]
    assert all(finding.target_id == _ASSET for finding in result.findings)
    assert all(finding.status is DefectStatus.SUSPECTED for finding in result.findings)
    assert all(finding.human_decision_id is None for finding in result.findings)
    assert all(finding.detector == "provider.fixture_visual.visual.generative_defects" for finding in result.findings)
    assert provider.calls == 1


def test_result_serialization_is_deterministic_and_privacy_safe():
    provider = _Provider(_batch(_proposal()))
    kwargs = {
        "playable_end": 10.0,
        "capability_id": "visual.generative_defects",
        "provider_id": "fixture_visual",
        "project_id": "project-7",
        "created_by": "agent:inspection",
        "registry": _registry(provider),
    }

    first = analyze_optional_visual_findings(_package(), **kwargs)
    second = analyze_optional_visual_findings(_package(), **kwargs)
    encoded = json.dumps(first.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    assert first == second
    assert "host_secret_location" not in encoded
    assert "factory" not in encoded
    assert "payload" not in encoded


@pytest.mark.parametrize(
    "payload",
    [
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [],
            "secret_path": "host_secret_location",
        },
        {
            "provider_id": "other_provider",
            "capability_id": "visual.generative_defects",
            "findings": [],
        },
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.motion_intent",
            "findings": [],
        },
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [
                {
                    "defect_code": "warping",
                    "time_range": [1.0, 2.0],
                    "severity": "high",
                    "confidence": 0.8,
                    "evidence_artifact_ids": [_EVIDENCE_A],
                    "status": "confirmed",
                }
            ],
        },
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [
                {
                    "defect_code": "warping",
                    "time_range": [1.0, 2.0],
                    "severity": "high",
                    "confidence": 0.8,
                    "evidence_artifact_ids": ["sha256:" + "d" * 64],
                }
            ],
        },
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [
                {
                    "defect_code": "warping",
                    "time_range": [1.0, 2.0],
                    "severity": "high",
                    "confidence": 0.8,
                    "measurements": [{"name": "host-secret-location", "value": 1.0, "unit": "score"}],
                    "evidence_artifact_ids": [_EVIDENCE_A],
                }
            ],
        },
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [
                {
                    "defect_code": "warping",
                    "time_range": [1.0, 2.0],
                    "severity": "high",
                    "confidence": 0.8,
                    "evidence_artifact_ids": [],
                }
            ],
        },
    ],
)
def test_hostile_provider_output_is_rejected_without_echoing_values(payload):
    provider = _Provider(payload)

    with pytest.raises(MCPVideoError) as exc:
        analyze_optional_visual_findings(
            _package(),
            playable_end=10.0,
            capability_id="visual.generative_defects",
            provider_id="fixture_visual",
            project_id="project-7",
            created_by="agent:inspection",
            registry=_registry(provider),
        )

    assert exc.value.code == "inspection_provider_output_invalid"
    assert "host_secret_location" not in str(exc.value)
    assert "host-secret-location" not in str(exc.value)
    assert "other_provider" not in str(exc.value)


def test_provider_failure_is_redacted_and_returns_typed_unavailable():
    class FailingProvider(_Provider):
        def analyze(self, package, capability_id):
            raise RuntimeError("credential and host_secret_location")

    result = analyze_optional_visual_findings(
        _package(),
        playable_end=10.0,
        capability_id="visual.generative_defects",
        provider_id="fixture_visual",
        project_id="project-7",
        created_by="agent:inspection",
        registry=_registry(FailingProvider(None)),
    )

    assert result.status == "capability_unavailable"
    assert result.capability.reason_code == "provider_failed"
    assert "host_secret_location" not in result.model_dump_json()
    assert "credential" not in result.model_dump_json()


def test_provider_constructor_failure_is_redacted_and_fails_soft():
    def fail_factory():
        raise ImportError("optional model missing at host_secret_location")

    registry = ProviderRegistry((ProviderDefinition(provider_id="fixture_visual", factory=fail_factory),))

    result = analyze_optional_visual_findings(
        _package(),
        playable_end=10.0,
        capability_id="visual.generative_defects",
        provider_id="fixture_visual",
        project_id="project-7",
        created_by="agent:inspection",
        registry=registry,
    )

    assert result.status == "capability_unavailable"
    assert result.capability.reason_code == "provider_failed"
    assert "host_secret_location" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("project_id", "created_by"),
    [("", "agent:inspection"), ("project-7", "not-an-actor")],
)
def test_invalid_normalization_context_maps_to_custom_error(project_id, created_by):
    provider = _Provider(_batch(_proposal()))

    with pytest.raises(MCPVideoError) as exc:
        analyze_optional_visual_findings(
            _package(),
            playable_end=10.0,
            capability_id="visual.generative_defects",
            provider_id="fixture_visual",
            project_id=project_id,
            created_by=created_by,
            registry=_registry(provider),
        )

    assert exc.value.code == "inspection_provider_request_invalid"


def test_registry_is_static_typed_and_rejects_config_driven_identifiers():
    provider = _Provider(_batch())
    with pytest.raises(MCPVideoError):
        ProviderRegistry(
            (
                ProviderDefinition(
                    provider_id="module.Provider",
                    factory=lambda: provider,
                ),
            )
        )
    with pytest.raises(MCPVideoError):
        ProviderRegistry(
            (
                ProviderDefinition(provider_id="fixture_visual", factory=lambda: provider),
                ProviderDefinition(provider_id="fixture_visual", factory=lambda: provider),
            )
        )


def test_factory_identity_and_capability_claims_are_validated_privately():
    class HostileProvider(_Provider):
        provider_id = "different_provider"

    for provider in (
        HostileProvider(_batch()),
        type(
            "BadCapabilities",
            (),
            {
                "provider_id": "fixture_visual",
                "capability_ids": ("visual.unknown",),
                "analyze": lambda self, package, capability_id: _batch(),
            },
        )(),
    ):
        with pytest.raises(MCPVideoError) as exc:
            analyze_optional_visual_findings(
                _package(),
                playable_end=10.0,
                capability_id="visual.generative_defects",
                provider_id="fixture_visual",
                project_id="project-7",
                created_by="agent:inspection",
                registry=_registry(provider),
            )
        assert exc.value.code == "inspection_provider_invalid"
        assert "different_provider" not in str(exc.value)


def test_provider_not_supporting_requested_capability_is_typed_unavailable():
    provider = _Provider(_batch())
    provider.capability_ids = ("visual.motion_intent",)

    result = analyze_optional_visual_findings(
        _package(),
        playable_end=10.0,
        capability_id="visual.generative_defects",
        provider_id="fixture_visual",
        project_id="project-7",
        created_by="agent:inspection",
        registry=_registry(provider),
    )

    assert result.status == "capability_unavailable"
    assert result.capability.reason_code == "capability_not_supported"
    assert provider.calls == 0


def test_provider_finding_may_end_exactly_at_trusted_playable_end():
    provider = _Provider(_batch(_proposal(time_range=(1.0, 2.0))))

    result = analyze_optional_visual_findings(
        _package(),
        playable_end=2.0,
        capability_id="visual.generative_defects",
        provider_id="fixture_visual",
        project_id="project-7",
        created_by="agent:inspection",
        registry=_registry(provider),
    )

    assert result.playable_end == 2.0
    assert result.findings[0].time_range == (1.0, 2.0)


@pytest.mark.parametrize("overflow_end", [10.000001, 1e9, 1e300, float("inf"), float("nan")])
def test_provider_timestamp_cannot_exceed_trusted_playable_end(overflow_end):
    provider = _Provider(
        {
            "provider_id": "fixture_visual",
            "capability_id": "visual.generative_defects",
            "findings": [
                {
                    "defect_code": "warping",
                    "time_range": [1.0, overflow_end],
                    "severity": "high",
                    "confidence": 0.8,
                    "evidence_artifact_ids": [_EVIDENCE_A],
                }
            ],
        }
    )

    with pytest.raises(MCPVideoError) as exc:
        analyze_optional_visual_findings(
            _package(),
            playable_end=10.0,
            capability_id="visual.generative_defects",
            provider_id="fixture_visual",
            project_id="project-7",
            created_by="agent:inspection",
            registry=_registry(provider),
        )

    assert exc.value.code == "inspection_provider_output_invalid"
    assert str(overflow_end) not in str(exc.value)


@pytest.mark.parametrize(
    "playable_end",
    [0.0, -1.0, 1e9, 1e300, float("inf"), float("nan")],
)
def test_trusted_playable_end_must_be_finite_positive_and_within_video_limit(playable_end):
    with pytest.raises(MCPVideoError) as exc:
        analyze_optional_visual_findings(
            _package(),
            playable_end=playable_end,
            capability_id="visual.motion_intent",
            provider_id=None,
            project_id="project-7",
            created_by="agent:inspection",
        )

    assert exc.value.code == "inspection_provider_request_invalid"
