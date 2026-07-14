"""Integration test: a SoundPlan and its receipt serialize without leaks.

This test exercises the canonical S1 use case end-to-end:

* A SoundPlan is built from the typed contracts (timeline, lines, routing,
  format, delivery, provenance) and carries a stable canonical id.
* A SoundReceiptSection is built with the plan hash, profile versions, consent
  grant references, and loudness verification.
* A SoundReceipt wraps a legacy v1 edit-receipt dict and carries the additive
  ``sound`` section under a single key.
* The serialized receipt exposes no host path, raw prompt, transcript, subject
  identity, biometric material, or credential — by construction.
"""

from __future__ import annotations


from kinocut_sound import (
    AudioFormat,
    ChannelLayout,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    ConversionPolicy,
    Cue,
    CueKind,
    DeliveryPolicy,
    DitherPolicy,
    Emotion,
    Line,
    LoudnessVerification,
    OrderedInput,
    PanLaw,
    PlanProvenance,
    ProfileRef,
    PronunciationOverride,
    Prosody,
    RetentionPolicy,
    Routing,
    SampleFormat,
    SoundPlan,
    SoundReceipt,
    SoundReceiptSection,
    TimeBase,
    Timeline,
    Track,
    Bus,
)
from kinocut_sound._canonical import canonical_digest

_SHA = "sha256:" + "9" * 64
_GRANT_HASH = "sha256:" + "a" * 64


def _format() -> AudioFormat:
    return AudioFormat(
        channel_layout=ChannelLayout.STEREO,
        sample_rate_hz=48000,
        sample_format=SampleFormat.PCM_S24LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.TRIANGULAR,
    )


def _line() -> Line:
    return Line(
        line_id="line_001",
        character_id="character_narrator",
        profile=ProfileRef(profile_id="voice_narrator", version=2),
        text_hash=_SHA,
        text_length_chars=128,
        prosody=Prosody(rate=0.95, pitch=-1.0),
        emotion=Emotion(label="confessional_dread", intensity=0.6),
        spatial_preset="close_mic_dry",
        pronunciation_overrides=(PronunciationOverride(term_hash=_SHA, ipa="kon.fɛ.ʃən.al"),),
        inherit_loudness=True,
    )


def _plan() -> SoundPlan:
    return SoundPlan(
        project_id="proj-witnessed-fate",
        episode_id="episode_pilot",
        format=_format(),
        timeline=Timeline(
            cues=(
                Cue(
                    cue_id="cue_001",
                    start_seconds=0.0,
                    duration_seconds=12.5,
                    kind=CueKind.LINE,
                    source_ref="lines/line_001.json",
                ),
                Cue(
                    cue_id="cue_silence_001",
                    start_seconds=12.5,
                    duration_seconds=0.5,
                    kind=CueKind.SILENCE,
                    source_ref="silence/room_tone.json",
                ),
            ),
            tail_seconds=1.0,
        ),
        lines=(_line(),),
        beds=("bed_room_small",),
        layers=("layer_foley_step",),
        routing=Routing(
            tracks=(
                Track(
                    track_id="track_dialog_001",
                    destination_bus_id="bus_dialog",
                    gain_db=-1.5,
                    pan_law=PanLaw.LINEAR,
                    muted=False,
                    soloed=False,
                ),
            ),
            buses=(Bus(bus_id="bus_dialog", kind="dialog"),),
        ),
        delivery=DeliveryPolicy(),
        provenance=PlanProvenance(
            consent_grant_refs=("grant_001",),
            transcript_hashes=(_SHA,),
        ),
        created_by="agent:worker_1",
    )


def test_sidecar_boundary_kinocut_sound_does_not_import_kinocut_runtime():
    # The sidecar must remain usable without any ``kinocut`` runtime import. A
    # static AST scan of every module in the package catches both
    # ``import kinocut`` and ``from kinocut...`` forms at the source level —
    # which ``sys.modules`` cannot, once any other test has loaded kinocut.
    import ast
    import kinocut_sound
    from pathlib import Path

    package_root = Path(kinocut_sound.__file__).resolve().parent
    offenders: dict[str, list[str]] = {}
    for module_path in sorted(package_root.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        bad: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "kinocut" or node.module.startswith("kinocut."))
            ):
                bad.append(f"from {node.module} import ...")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut" or alias.name.startswith("kinocut."):
                        bad.append(f"import {alias.name}")
        if bad:
            offenders[module_path.name] = bad
    assert offenders == {}, "kinocut_sound must not import the kinocut runtime; sidecar boundary broken: " + repr(
        offenders
    )


def test_canonical_plan_id_is_stable_across_construction_instances():
    a = _plan()
    b = _plan()
    assert a.canonical_id() == b.canonical_id()
    # created_at drift does not change identity.
    c = a.model_copy(update={"created_at": "2030-12-31T00:00:00Z"})
    assert c.canonical_id() == a.canonical_id()


def test_receipt_serializes_sound_section_without_leaks():
    plan = _plan()
    section = SoundReceiptSection(
        plan_hash=plan.canonical_id(),
        profile_versions=(("voice_narrator", 2),),
        consent_grant_refs=("grant_001",),
        loudness=LoudnessVerification(
            preset="stream_-14",
            integrated_lufs=-14.02,
            true_peak_dbtp=-1.05,
            lra_lu=7.5,
            within_tolerance=True,
        ),
        ordered_inputs=(
            OrderedInput(
                asset_id=_SHA,
                input_hash=_SHA,
                role="dialog_clip",
                safe_display_name="lines/line_001",
                in_point=0.0,
                out_point=12.5,
                probed_duration=12.5,
            ),
        ),
        warnings=(),
        human_review_required=True,
    )
    receipt = SoundReceipt.from_legacy(
        {
            "schema_version": 1,
            "operation": "episode_render",
            "normalized_parameters": {"episode": "pilot"},
            "inputs": [],
            "output_hash": _SHA,
            "warnings": [],
        },
        section,
    )
    serialized = receipt.model_dump_json()
    assert "sound" in serialized
    assert "grant_001" in serialized
    # Structural leak audit: none of these may ever appear.
    for forbidden in (
        "/home/",
        "/etc/",
        "/Users/",
        "AKIA",  # AWS access key prefix
        "sk-",  # common API key prefix
        "password",
        "subject_001",  # subject identity stays in the ledger
        "raw_prompt",
        "raw_transcript",
    ):
        assert forbidden not in serialized, f"forbidden token leaked: {forbidden!r}"


def test_consent_grant_does_not_carry_biometric_material_into_plan_provenance():
    # A ConsentGrant's subject_id is referenced only by opaque id in a plan.
    # Use a hash distinct from the plan's transcript hash so the assertion is
    # non-tautological (the plan uses _SHA for its transcript_hashes).
    grant = ConsentGrant(
        grant_id="grant_001",
        subject_id="subject_001",
        rightsholder_id="rightsholder_001",
        scope=ConsentScope(
            project_ids=("proj-witnessed-fate",),
            character_ids=("character_narrator",),
            operations=("voice_clone",),
            provider_classes=("local",),
            territory="US",
        ),
        reference_evidence_hash=_GRANT_HASH,
        transcript_evidence_hash=_GRANT_HASH,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(biometric_retention="delete_after_use", audit_retention="keep_5y"),
    )
    plan = _plan()
    # The plan references the grant by opaque id only.
    assert "grant_001" in plan.model_dump_json()
    # The plan's serialized form does NOT carry subject_id, biometric material,
    # or the grant's reference/transcript evidence hashes (only the plan-level
    # transcript hash _SHA is present, which is distinct from _GRANT_HASH).
    plan_json = plan.model_dump_json()
    assert "subject_001" not in plan_json
    assert _GRANT_HASH not in plan_json
    # The grant itself does carry reference_evidence_hash by design (it is the
    # private ledger artifact, not the durable plan). The grant carries the
    # *policy* on biometric retention but never raw biometric bytes — assert
    # the field set never names a raw-bytes payload.
    grant_field_names = set(type(grant).model_fields.keys())
    assert "biometric_bytes" not in grant_field_names
    assert "reference_audio_bytes" not in grant_field_names
    assert "embedding_bytes" not in grant_field_names
    assert "raw_prompt" not in grant_field_names
    # And the serialized grant carries the retention policy (bounded code) but
    # never raw biometric data: there is no field that could hold it.
    grant_json = grant.model_dump_json()
    assert "reference_evidence_hash" in grant_json  # hash only, by design
    assert "biometric_retention" in grant_json  # policy code, not data
    assert "biometric_data" not in grant_json


def test_canonical_digest_dict_path_matches_canonical_record_id_path():
    plan = _plan()
    via_record = plan.canonical_id()
    # Direct dict digest over the model dump (excluding record_id + created_at)
    # matches the record-path computation — proving the two code paths agree.
    payload = plan.model_dump(mode="json", exclude={"record_id", "created_at"})
    assert via_record == canonical_digest(payload)
