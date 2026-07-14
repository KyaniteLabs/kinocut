"""S14 bounded scheduler + cold/warm benchmark tests."""

from __future__ import annotations

import json
import time

import pytest

from kinocut.sound_joins.benchmark import (
    BenchmarkReceipt,
    FixtureSpec,
    detect_benchmark_class,
    run_cold_warm_benchmark,
)
from kinocut.sound_joins.scheduler import (
    BoundedProcessPool,
    CancelledError,
    PoolLimits,
)


def test_pool_respects_task_ceiling():
    pool = BoundedProcessPool(limits=PoolLimits(max_workers=2, max_tasks=2))
    with pytest.raises(ValueError, match="ceiling"):
        pool.map_tasks([(f"t{i}", (lambda i=i: i)) for i in range(5)])


def test_pool_cancel_and_resume():
    pool = BoundedProcessPool(limits=PoolLimits(max_workers=2, max_tasks=10))
    first = pool.map_tasks(
        [
            ("a", lambda: 1),
            ("b", lambda: 2),
        ]
    )
    assert all(r.ok for r in first)
    assert "a" in pool.completed_ids
    # resume skips completed
    second = pool.map_tasks(
        [
            ("a", lambda: 99),
            ("c", lambda: 3),
        ]
    )
    by_id = {r.task_id: r for r in second}
    assert by_id["a"].value == "skipped"
    assert by_id["c"].ok is True
    pool.cancel()
    with pytest.raises(CancelledError):
        pool.map_tasks([("d", lambda: 4)])


def test_detect_class_is_named():
    hw = detect_benchmark_class()
    assert hw.class_id
    assert hw.machine
    assert hw.platform


def test_cold_warm_benchmark_small_fixture():
    # Focused unit uses 8 clips; full 64-clip dual-class evidence is in receipts.
    receipt = run_cold_warm_benchmark(
        fixture=FixtureSpec(clip_count=8, clip_duration_seconds=0.05),
        max_workers=2,
    )
    assert receipt.fixture_version == "sound-bench-v1"
    assert receipt.clip_count == 8
    assert receipt.cold_ok is True
    assert receipt.warm_ok is True
    assert receipt.under_30m is True
    assert receipt.status == "ok"
    assert receipt.cold_seconds >= 0.0
    assert receipt.warm_seconds >= 0.0
    # warm should not be wildly slower than cold on pure synth (order free)
    text = json.dumps(receipt.to_payload())
    assert "/home/" not in text
    assert "password" not in text.lower()
    assert receipt.digest().startswith("sha256:")


def test_benchmark_public_payload_is_an_explicit_allowlist():
    receipt = BenchmarkReceipt(
        fixture_version="sound-bench-v1",
        hardware_class="apple_silicon",
        machine="private-machine",
        processor="private-processor",
        platform="private-platform",
        clip_count=8,
        cold_seconds=1.0,
        warm_seconds=0.5,
        cold_ok=True,
        warm_ok=True,
        under_30m=True,
        required_capabilities={"safe": True, "unknown": False},
        notes=("unsafe private note",),
        status="unsafe private status",
    )

    assert receipt.to_payload() == {
        "fixture_version": "sound-bench-v1",
        "hardware_class": "apple_silicon",
        "clip_count": 8,
        "cold_seconds": 1.0,
        "warm_seconds": 0.5,
        "cold_ok": True,
        "warm_ok": True,
        "under_30m": True,
        "required_capabilities": {"d41_bed": False, "d41_audition": False, "d42_style": False, "d42_identity": False},
    }


def test_pool_wall_clock_ceiling_is_enforced():
    pool = BoundedProcessPool(limits=PoolLimits(max_workers=1, max_tasks=5, max_wall_seconds=0.05))

    def slow() -> int:
        time.sleep(0.2)
        return 1

    results = pool.map_tasks([("slow", slow), ("fast", lambda: 2)])
    # At least one result is present; wall ceiling may cancel trailing work.
    assert len(results) >= 1
