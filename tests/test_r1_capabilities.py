from __future__ import annotations

from mcp_video.rescue.r1.capabilities import extend_capability_snapshot
from mcp_video.rescue.r1.models import ExecutorCapability, ModelCapability


def test_capability_extension_is_additive_and_does_not_mutate_base() -> None:
    base = {"local_only": True, "ffmpeg": {"available": True}, "filters": {"eq": True}}

    extended = extend_capability_snapshot(
        base,
        executors=(
            ExecutorCapability(
                id="opencv.crop_tracker",
                version="1.0",
                hardware=("cpu",),
                determinism_scope="same executor, version, hardware, and inputs",
            ),
        ),
        models=(
            ModelCapability(
                id="toy.crop",
                version="1.0",
                sha256="sha256:" + "1" * 64,
                hardware=("cpu",),
                determinism_scope="fixture-only",
            ),
        ),
    )

    assert tuple(base) == ("local_only", "ffmpeg", "filters")
    assert extended["ffmpeg"] == base["ffmpeg"]
    assert extended["extension_registry"]["executors"][0]["id"] == "opencv.crop_tracker"
    assert extended["extension_registry"]["models"][0]["sha256"].startswith("sha256:")
