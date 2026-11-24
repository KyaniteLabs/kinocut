"""Whole fields reject suffix controls without normalizing valid identities."""

from dataclasses import replace
import pytest
from pydantic import ValidationError

from kinocut_sound._canonical import BoundedCode, RecordBase
from kinocut_sound.capability import CapabilityResult, CostDisclosure
from kinocut_sound.consent import AuditEvent, CloudEgressGrant, ConsentGrant, ConsentScope, RetentionPolicy
from kinocut_sound.render_fingerprint import FingerprintComponent, RenderFingerprint
from kinocut_sound.public.mix_request import SourceAsset
from kinocut_sound.routing import Track
from kinocut_sound.timeline import Cue
from kinocut_sound.world.layers import AmbientLayer
from kinocut_sound.voice.roster import _BASE_ROSTER, _validate_slot
from kinocut_sound.voice._errors import VoiceError

SHA = "sha256:" + "a" * 64
NOW = "2026-01-01T00:00:00Z"
CONTROLS = ("\n", "\r\n", "\r", "\t", "\0", "\u2028")


def _cases():
    scope = ConsentScope(territory="US", intended_use_summary="A short preview.")
    grant = ConsentGrant(
        grant_id="grant",
        subject_id="subject",
        rightsholder_id="owner",
        scope=scope,
        reference_evidence_hash=SHA,
        transcript_evidence_hash=SHA,
        reviewer_id="reviewer",
        issue_iso=NOW,
        expiry_iso="2027-01-01T00:00:00Z",
        state="live",
        retention=RetentionPolicy(biometric_retention="delete", audit_retention="retain"),
    )
    cloud = CloudEgressGrant(
        provider_id="provider", data_classes=("audio",), territory="US", retention_ceiling_days=0, expiry_iso=NOW
    )
    cost = CostDisclosure(
        provider_id="provider",
        region="us-east-1",
        data_classes=("audio",),
        retention_ceiling_days=0,
        estimated_cost_usd_per_call=0,
        confirmed=False,
    )
    fingerprint = RenderFingerprint(
        determinism_class="byte_deterministic",
        seed="0",
        locale="en_US",
        hardware_backend="cpu",
        concurrency_ordering="serial",
        components=(FingerprintComponent(role="plan", digest=SHA),),
    )
    return [
        (scope, "territory"),
        (scope, "intended_use_summary"),
        (AuditEvent(event="issued", actor="human", at_iso=NOW), "at_iso"),
        (cloud, "territory"),
        (cloud, "expiry_iso"),
        (grant, "issue_iso"),
        (grant, "expiry_iso"),
        (cost, "region"),
        (
            CapabilityResult(
                adapter_id="local", available=False, reason_code="missing", remediation="Install optional tools."
            ),
            "remediation",
        ),
        (fingerprint, "locale"),
        (Cue(cue_id="cue", source_ref="clip.wav", start_seconds=0, duration_seconds=1, kind="line"), "cue_id"),
        (
            Track(
                track_id="track", destination_bus_id="dialogue", pan_law="linear", gain_db=0, muted=False, soloed=False
            ),
            "track_id",
        ),
        (AmbientLayer(layer_id="layer", asset_ref="rain"), "layer_id"),
    ]


@pytest.mark.parametrize(
    "model,field", _cases(), ids=lambda item: type(item).__name__ if not isinstance(item, str) else item
)
@pytest.mark.parametrize("suffix", CONTROLS)
def test_model_fields_reject_suffix_controls(model, field, suffix):
    raw = model.model_dump(mode="python")
    assert type(model).model_validate(raw).model_dump(mode="python") == raw
    raw[field] += suffix
    with pytest.raises(ValidationError):
        type(model).model_validate(raw)


@pytest.mark.parametrize("suffix", CONTROLS)
def test_shared_codes_and_roster_labels_reject_controls(suffix):
    with pytest.raises(ValueError):
        BoundedCode("cue-a" + suffix)
    slot = _BASE_ROSTER[0]
    with pytest.raises(VoiceError):
        _validate_slot(replace(slot, display_label=slot.display_label + suffix))


@pytest.mark.parametrize(
    "model,base,field",
    [
        (SourceAsset, {"path": "clip.wav", "sha256": SHA}, "sha256"),
        (RecordBase, {"record_kind": "line", "project_id": "demo", "created_by": "human"}, "record_kind"),
        (RecordBase, {"record_kind": "line", "project_id": "demo", "created_by": "human"}, "created_by"),
    ],
)
@pytest.mark.parametrize("suffix", CONTROLS)
def test_pydantic_patterns_remain_strict(model, base, field, suffix):
    model(**base)
    with pytest.raises(ValidationError) as error:
        model(**{**base, field: base[field] + suffix})
    assert any(item["type"] == "string_pattern_mismatch" for item in error.value.errors())
