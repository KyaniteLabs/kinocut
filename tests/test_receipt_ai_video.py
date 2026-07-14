"""Additive ``ai_video`` receipt section + preservation proofs (Plan 00 Task 5).

The section is a nested, additive key on an existing receipt dict: attaching it
never mutates or removes any legacy top-level field, and reading it back yields
the typed section (or ``None`` when absent). All values are ids, hashes, enums,
and numbers — never raw prompts or host paths — and invalid content surfaces as
a stable :class:`MCPVideoError` through the shared validation adapter.
"""

from __future__ import annotations

import pytest

from kinocut.contracts._errors import INVALID_RECORD, UNKNOWN_RECORD_FIELD
from kinocut.contracts.receipt_ai_video import (
    AiVideoReceiptSection,
    OrderedInput,
    PreservationProof,
    Transformation,
)
from kinocut.errors import MCPVideoError
from kinocut.receipts_ai_video import attach_ai_video_section, read_ai_video_section

_SHA = "sha256:" + "0" * 64
_ASSET = "sha256:" + "c" * 64


def _sample_section(**overrides) -> AiVideoReceiptSection:
    data = {
        "project_id": "proj-alpha",
        "acceptance_spec_id": _SHA,
        "ordered_inputs": (
            OrderedInput(
                asset_id=_ASSET, input_hash=_SHA, in_point=0.0, out_point=1.0, probed_duration=1.0, role="hero"
            ),
        ),
        "transformations": (
            Transformation(
                tool="ffmpeg",
                operation="trim",
                params_hash=_SHA,
                toolchain_versions=("ffmpeg-7.0",),
                output_duration=1.0,
                output_hash=_SHA,
                warnings=(),
            ),
        ),
        "duration_policy": "preserve",
        "preservation_proofs": (
            PreservationProof(
                expected="audio_stream_identical",
                method="packet_fingerprint",
                source_fingerprint=_SHA,
                output_fingerprint=_SHA,
                verdict="preserved",
            ),
        ),
        "finding_ids": (),
        "review_artifact_ids": (),
        "approval_state_id": None,
        "warnings": (),
    }
    data.update(overrides)
    return AiVideoReceiptSection(**data)


def test_ai_video_section_is_nested_and_additive():
    legacy = {"schema_version": 1, "receipt_kind": "workflow", "steps": [], "outputs": []}
    merged = attach_ai_video_section(dict(legacy), _sample_section())
    assert merged["receipt_kind"] == "workflow"  # unchanged
    assert set(legacy).issubset(merged)  # nothing removed
    assert merged["ai_video"]["contract_version"] == 1


def test_attach_does_not_mutate_input_receipt():
    legacy = {"schema_version": 1, "receipt_kind": "workflow", "steps": [], "outputs": []}
    original = dict(legacy)
    attach_ai_video_section(legacy, _sample_section())
    assert legacy == original  # caller's dict untouched
    assert "ai_video" not in legacy


def test_attach_refuses_to_clobber_existing_section():
    legacy = {"schema_version": 1, "receipt_kind": "workflow"}
    once = attach_ai_video_section(legacy, _sample_section())
    with pytest.raises(MCPVideoError):
        attach_ai_video_section(once, _sample_section())


def test_read_section_roundtrips():
    legacy = {"schema_version": 1, "receipt_kind": "workflow"}
    merged = attach_ai_video_section(legacy, _sample_section())
    section = read_ai_video_section(merged)
    assert isinstance(section, AiVideoReceiptSection)
    assert section.project_id == "proj-alpha"
    assert section.preservation_proofs[0].verdict == "preserved"


def test_read_absent_section_returns_none():
    assert read_ai_video_section({"schema_version": 1, "receipt_kind": "workflow"}) is None


def test_read_invalid_section_maps_to_contract_error():
    receipt = {"receipt_kind": "workflow", "ai_video": {"contract_version": 1}}  # missing required
    with pytest.raises(MCPVideoError) as excinfo:
        read_ai_video_section(receipt)
    assert excinfo.value.code == INVALID_RECORD


def test_read_unknown_field_in_section_maps_to_unknown_field_code():
    section_dict = _sample_section().model_dump(mode="json")
    section_dict["surprise"] = True
    with pytest.raises(MCPVideoError) as excinfo:
        read_ai_video_section({"receipt_kind": "workflow", "ai_video": section_dict})
    assert excinfo.value.code == UNKNOWN_RECORD_FIELD


def test_contract_version_frozen_to_one():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _sample_section(contract_version=2)


def test_preservation_proof_states_expected_and_verdict():
    proof = PreservationProof(
        expected="audio_stream_identical",
        method="packet_fingerprint",
        source_fingerprint=_SHA,
        output_fingerprint=_SHA,
        verdict="preserved",
    )
    assert proof.verdict in {"preserved", "changed"}


def test_preservation_proof_verdict_is_closed():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PreservationProof(expected="x", method="m", source_fingerprint=_SHA, output_fingerprint=_SHA, verdict="maybe")


def test_section_rejects_unknown_field_on_construction():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _sample_section(surprise=True)


def test_section_carries_no_home_path():
    from pathlib import Path

    dumped = _sample_section().model_dump_json()
    assert str(Path.home()) not in dumped


# ---- Receipt review: strict numbers, safe text, attach safety --------------

from pydantic import ValidationError  # noqa: E402


def test_contract_version_is_strict_integer():
    for bad in (True, 1.0, "1"):
        with pytest.raises(ValidationError):
            _sample_section(contract_version=bad)


def test_ordered_input_points_must_be_nonnegative_and_ordered():
    with pytest.raises(ValidationError):
        OrderedInput(asset_id=_ASSET, input_hash=_SHA, in_point=-0.1, out_point=1.0, probed_duration=1.0, role="hero")
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_ASSET, input_hash=_SHA, in_point=1.0, out_point=1.0, probed_duration=1.0, role="hero"
        )  # not ordered / zero length
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_ASSET, input_hash=_SHA, in_point=0.0, out_point=1.0, probed_duration=-1.0, role="hero"
        )  # negative duration
    ok = OrderedInput(asset_id=_ASSET, input_hash=_SHA, in_point=0.0, out_point=1.0, probed_duration=1.0, role="hero")
    assert ok.out_point == 1.0


def test_transformation_output_duration_must_be_nonnegative():
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", output_duration=-1.0)
    ok = Transformation(tool="ffmpeg", operation="trim", output_duration=1.0)
    assert ok.output_duration == 1.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "a\x00b"),  # NUL / control char
        ("tool", "/Users/victim/ffmpeg"),  # host path
        ("operation", "http://evil.test"),  # URL scheme
        ("method", "../../etc/passwd"),  # traversal
    ],
)
def test_hostile_free_text_is_rejected(field, value):
    kwargs = {
        "asset_id": _ASSET,
        "input_hash": _SHA,
        "in_point": 0.0,
        "out_point": 1.0,
        "probed_duration": 1.0,
        "role": "hero",
    }
    if field == "role":
        kwargs["role"] = value
        with pytest.raises(ValidationError):
            OrderedInput(**kwargs)
    elif field in ("tool", "operation"):
        with pytest.raises(ValidationError):
            Transformation(**{"tool": "ffmpeg", "operation": "trim", field: value})
    else:  # method
        with pytest.raises(ValidationError):
            PreservationProof(
                expected="ok", method=value, source_fingerprint=_SHA, output_fingerprint=_SHA, verdict="preserved"
            )


def test_warning_strings_reject_host_paths():
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", warnings=("clip failed at /home/victim/secret.mp4",))


def test_preservation_expected_rejects_secret_like_text():
    with pytest.raises(ValidationError):
        PreservationProof(
            expected="token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
            method="packet_fingerprint",
            source_fingerprint=_SHA,
            output_fingerprint=_SHA,
            verdict="preserved",
        )


def test_attach_rejects_wrong_section_type():
    with pytest.raises(MCPVideoError):
        attach_ai_video_section({"receipt_kind": "workflow"}, {"not": "a section"})


def test_attach_rejects_non_dict_receipt():
    with pytest.raises(MCPVideoError):
        attach_ai_video_section(["not", "a", "dict"], _sample_section())


def test_attach_deep_copy_independence():
    receipt = {"receipt_kind": "workflow", "nested": {"items": ["a"]}}
    merged = attach_ai_video_section(receipt, _sample_section())
    merged["nested"]["items"].append("b")
    assert receipt["nested"]["items"] == ["a"]  # original nested list untouched


# ---- Re-review round 2: strict times, coherent ranges, deeper privacy ------


def test_string_time_values_are_rejected():
    with pytest.raises(ValidationError):
        OrderedInput(asset_id=_ASSET, input_hash=_SHA, in_point="0.0", out_point=1.0, probed_duration=1.0, role="hero")
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", output_duration="2.0")


def test_out_point_must_not_exceed_probed_duration():
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_ASSET, input_hash=_SHA, in_point=0.0, out_point=2.0, probed_duration=1.0, role="hero"
        )  # out beyond probed length
    ok = OrderedInput(asset_id=_ASSET, input_hash=_SHA, in_point=0.0, out_point=1.0, probed_duration=1.0, role="hero")
    assert ok.out_point == 1.0


def test_in_point_must_not_exceed_probed_duration_even_without_out():
    with pytest.raises(ValidationError):
        OrderedInput(
            asset_id=_ASSET, input_hash=_SHA, in_point=2.0, out_point=None, probed_duration=1.0, role="hero"
        )  # in beyond probed length, no out


@pytest.mark.parametrize(
    "text",
    [
        "/etc/passwd",
        "/private/tmp/leak.mp4",
        "/var/folders/xy/z",
        "/Volumes/Private/client.mov",  # macOS external volume
        "prompt: cinematic portrait of a cat",
    ],
)
def test_embedded_host_path_or_prompt_text_rejected(text):
    # These land in a free-text (non-warning) field; every abs path root is caught.
    with pytest.raises(ValidationError):
        Transformation(tool=text, operation="trim")


def test_warnings_must_be_structured_codes_not_prose():
    # Arbitrary prose (e.g. a raw prompt) cannot serialize as a warning.
    with pytest.raises(ValidationError):
        Transformation(
            tool="ffmpeg",
            operation="trim",
            warnings=("cinematic portrait of a private client in her bedroom, warm light",),
        )
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", warnings=("/Volumes/Private/x.mov",))
    ok = Transformation(tool="ffmpeg", operation="trim", warnings=("audio_style_seam", "resolution_mismatch"))
    assert ok.warnings == ("audio_style_seam", "resolution_mismatch")


def test_section_warnings_must_be_structured_codes():
    with pytest.raises(ValidationError):
        _sample_section(warnings=("this is free prose that should not serialize",))


# ---- Every identity-like field is a closed bounded code (no prose anywhere) ----

_PROSE = "cinematic portrait of a private client in her bedroom warm light"


def test_unlabeled_prompt_prose_rejected_across_all_fields():
    with pytest.raises(ValidationError):
        OrderedInput(asset_id=_ASSET, input_hash=_SHA, role=_PROSE)
    with pytest.raises(ValidationError):
        Transformation(tool=_PROSE, operation="trim")
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation=_PROSE)
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", toolchain_versions=(_PROSE,))
    with pytest.raises(ValidationError):
        Transformation(tool="ffmpeg", operation="trim", warnings=(_PROSE,))
    with pytest.raises(ValidationError):
        PreservationProof(
            expected=_PROSE,
            method="packet_fingerprint",
            source_fingerprint=_SHA,
            output_fingerprint=_SHA,
            verdict="preserved",
        )
    with pytest.raises(ValidationError):
        PreservationProof(
            expected="audio_stream_identical",
            method=_PROSE,
            source_fingerprint=_SHA,
            output_fingerprint=_SHA,
            verdict="preserved",
        )
    with pytest.raises(ValidationError):
        _sample_section(project_id=_PROSE)
    with pytest.raises(ValidationError):
        _sample_section(duration_policy=_PROSE)


def test_bounded_codes_accept_normal_identifiers():
    # Sanity: real code-shaped values still validate.
    ok = Transformation(
        tool="ffmpeg", operation="trim", toolchain_versions=("ffmpeg-7.0", "libx264-r3"), warnings=("audio_style_seam",)
    )
    assert ok.tool == "ffmpeg"
