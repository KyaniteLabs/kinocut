"""Host-side sound joins (S13) and benchmark harness (S14).

Lives under ``kinocut`` so it may import both the Kinocut runtime and the
``kinocut_sound`` sidecar. The sidecar itself never imports ``kinocut.*``.

S13 binds existing D41 (``audio_bed``) and D42 (``voice_seam``) owners to the
neutral sound ports. S14 provides a bounded local scheduler and dual-class
cold/warm benchmark receipts. No release action is authorized here.
"""

from __future__ import annotations

from kinocut.sound_joins.benchmark import (
    BenchmarkClass,
    BenchmarkReceipt,
    FixtureSpec,
    run_cold_warm_benchmark,
)
from kinocut.sound_joins.d41_bind import (
    D41_AUDITION_KINOCUT_ADAPTER_ID,
    D41_BED_KINOCUT_ADAPTER_ID,
    KinocutAuditionAdapter,
    KinocutBedAdapter,
    KinocutD41Port,
    default_kinocut_d41_port,
)
from kinocut.sound_joins.d42_bind import (
    D42_IDENTITY_KINOCUT_ADAPTER_ID,
    D42_STYLE_KINOCUT_ADAPTER_ID,
    KinocutD42Port,
    KinocutIdentityAdapter,
    KinocutStyleAdapter,
    PathAssetIndex,
    default_kinocut_d42_port,
)
from kinocut.sound_joins.scheduler import (
    BoundedProcessPool,
    CancelledError,
    PoolLimits,
    TaskResult,
)

__all__ = [
    "D41_AUDITION_KINOCUT_ADAPTER_ID",
    "D41_BED_KINOCUT_ADAPTER_ID",
    "D42_IDENTITY_KINOCUT_ADAPTER_ID",
    "D42_STYLE_KINOCUT_ADAPTER_ID",
    "BenchmarkClass",
    "BenchmarkReceipt",
    "BoundedProcessPool",
    "CancelledError",
    "FixtureSpec",
    "KinocutAuditionAdapter",
    "KinocutBedAdapter",
    "KinocutD41Port",
    "KinocutD42Port",
    "KinocutIdentityAdapter",
    "KinocutStyleAdapter",
    "PathAssetIndex",
    "PoolLimits",
    "TaskResult",
    "default_kinocut_d41_port",
    "default_kinocut_d42_port",
    "run_cold_warm_benchmark",
]
