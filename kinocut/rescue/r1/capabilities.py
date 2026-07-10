"""Additive executor and model capability metadata."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .models import ExecutorCapability, ModelCapability


def extend_capability_snapshot(
    base: Mapping[str, Any],
    *,
    executors: tuple[ExecutorCapability, ...] = (),
    models: tuple[ModelCapability, ...] = (),
) -> dict[str, Any]:
    """Return an additive snapshot without probing, installing, or mutating inputs."""

    if "extension_registry" in base:
        raise ValueError("base capability snapshot already contains extension_registry")
    snapshot = copy.deepcopy(dict(base))
    snapshot["extension_registry"] = {
        "executors": [item.model_dump(mode="json") for item in sorted(executors, key=lambda item: item.id)],
        "models": [item.model_dump(mode="json") for item in sorted(models, key=lambda item: item.id)],
    }
    return snapshot
