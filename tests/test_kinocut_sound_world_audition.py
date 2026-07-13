"""Audition contract tests for the S8 world leaf.

Covers required row:
* audition contract produces a receipt with human_review_required.

Plus hardening: perceptual QA never auto-passes; the receipt carries no host
path or raw prompt; the receipt digest is deterministic.
"""

from __future__ import annotations

import pytest

from kinocut_sound.world import (
    AuditionContext,
    AuditionContract,
    AuditionRequest,
    WorldError,
)

_SHA = "sha256:" + "a" * 64


def _request(
    *,
    bed_id: str = "bed_common_room",
    reel_label: str = "reel_review_001",
    note_hash: str | None = _SHA,
    layer_ids: tuple[str, ...] = ("layer_hum", "layer_chatter"),
    target_duration_seconds: float | None = 120.0,
) -> AuditionRequest:
    return AuditionRequest(
        bed_id=bed_id,
        context=AuditionContext(
            reviewer_id="reviewer_001",
            project_id="proj_witnessed_fate",
            episode_id="episode_pilot",
            note_hash=note_hash,
        ),
        layer_ids=layer_ids,
        target_duration_seconds=target_duration_seconds,
        reel_label=reel_label,
    )


def test_audition_contract_produces_receipt_with_human_review_required():
    receipt = AuditionContract().audition(_request())
    assert receipt.human_review_required is True
    assert receipt.bed_id == "bed_common_room"
    assert receipt.reel_label == "reel_review_001"
    assert receipt.reviewer_id == "reviewer_001"
    assert receipt.reel_descriptor_hash.startswith("sha256:")


def test_audition_receipt_never_carries_raw_note_text_or_paths():
    receipt = AuditionContract().audition(_request())
    payload = receipt.to_payload()
    serialized = str(payload)
    # The note *hash* is present (in the descriptor), but the raw text never is.
    for forbidden in ("/home/", "/etc/", "password", "raw_note", "raw_prompt"):
        assert forbidden not in serialized
    # The hash is the only representation of the note.
    assert _SHA not in serialized or _SHA in receipt.reel_descriptor_hash


def test_audition_receipt_is_deterministic_for_identical_requests():
    contract = AuditionContract()
    a = contract.audition(_request())
    b = contract.audition(_request())
    assert a.reel_descriptor_hash == b.reel_descriptor_hash
    assert a.digest() == b.digest()
    # A different reviewer changes the hash.
    other = AuditionRequest(
        bed_id="bed_common_room",
        context=AuditionContext(
            reviewer_id="reviewer_002",
            project_id="proj_witnessed_fate",
            episode_id="episode_pilot",
        ),
        reel_label="reel_review_001",
    )
    assert contract.audition(other).reel_descriptor_hash != a.reel_descriptor_hash


def test_audition_rejects_non_positive_target_duration():
    with pytest.raises(WorldError) as exc:
        AuditionContract().audition(
            AuditionRequest(
                bed_id="bed_common_room",
                context=AuditionContext(
                    reviewer_id="rev_1",
                    project_id="proj",
                    episode_id="ep",
                ),
                reel_label="reel",
                target_duration_seconds=-1.0,
            )
        )
    assert exc.value.code == "audition_invalid"


def test_audition_request_rejects_unbounded_codes_and_duplicate_layers():
    with pytest.raises(Exception):
        AuditionRequest(
            bed_id="not a bounded id",
            context=AuditionContext(reviewer_id="rev_1", project_id="proj", episode_id="ep"),
            reel_label="reel",
        )
    with pytest.raises(Exception):
        AuditionRequest(
            bed_id="bed_x",
            context=AuditionContext(reviewer_id="rev_1", project_id="proj", episode_id="ep"),
            reel_label="reel",
            layer_ids=("layer_dup", "layer_dup"),
        )
