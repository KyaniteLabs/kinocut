"""S15 stop-gate smoke: privacy and non-release invariants."""

from __future__ import annotations

import json
from pathlib import Path

from kinocut.sound_joins.benchmark import BenchmarkReceipt
from kinocut_sound.public import discover_sound_capabilities, invoke_sound_operation


def test_public_payloads_have_no_host_paths_or_secrets():
    caps = invoke_sound_operation("sound-capabilities")
    text = json.dumps(caps)
    assert "/home/" not in text
    assert "api_key" not in text.lower()
    assert "password" not in text.lower()


def test_discovery_is_local_first():
    m = discover_sound_capabilities()
    assert m.local_first is True
    assert m.non_tty_json is True


def test_historical_gate_receipt_has_a_neutral_execution_boundary():
    receipt = Path("docs/status/2026-07-14-sound-s13-s15-gate-receipt.md")
    text = receipt.read_text(encoding="utf-8")
    assert "Commands executed after S12 merge:" in text
    assert "not final 1.8.0 release authorization" in text
    assert "Niko" not in text
    assert "Liam" not in text


def test_public_s14_evidence_matches_allowlisted_receipt_digests():
    evidence = json.loads(Path("docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json").read_text())
    assert set(evidence) == {"fixture_version", "clip_count", "classes"}
    for item in evidence["classes"]:
        digest = item.pop("digest")
        assert set(item) == {
            "fixture_version",
            "hardware_class",
            "clip_count",
            "cold_seconds",
            "warm_seconds",
            "cold_ok",
            "warm_ok",
            "under_30m",
            "required_capabilities",
        }
        receipt = BenchmarkReceipt(
            machine="",
            processor="",
            platform="",
            **item,
        )
        assert receipt.to_payload() == item
        assert receipt.digest() == digest
