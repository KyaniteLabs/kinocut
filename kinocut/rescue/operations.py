"""Closed operation adapters for policy-approved rescue repairs."""

from __future__ import annotations

import hashlib
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..engine_audio_normalize import normalize_audio
from ..engine_convert import convert
from ..engine_filters import apply_filter
from ..engine_rotate import rotate
from ..engine_transcode import normalize
from ._errors import RESCUE_POLICY_VIOLATION, UNSAFE_RESCUE_OUTPUT, rescue_error
from .models import Disposition, Repair, RepairType


@dataclass(frozen=True)
class OperationResult:
    """Persisted output identity from one bounded rescue operation."""

    operation: str
    output_path: str
    elapsed_ms: int
    sha256: str
    repair_id: str | None = None


@dataclass(frozen=True)
class OperationAdapter:
    allowed_parameters: frozenset[str]
    run: Callable[[str, str, Mapping[str, Any]], None]


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _number(parameters: Mapping[str, Any], name: str, default: float) -> float:
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise rescue_error(f"{name} must be numeric", RESCUE_POLICY_VIOLATION)
    return float(value)


def _run_rotation(input_path: str, output_path: str, parameters: Mapping[str, Any]) -> None:
    angle = _number(parameters, "angle", 0.0)
    if not angle.is_integer() or int(angle) % 360 not in {90, 180, 270}:
        raise rescue_error("rotation angle must normalize to 90, 180, or 270", RESCUE_POLICY_VIOLATION)
    rotate(input_path, angle=int(angle) % 360, output_path=output_path)


def _run_loudness(input_path: str, output_path: str, parameters: Mapping[str, Any]) -> None:
    target_lufs = _number(parameters, "target_lufs", -16.0)
    lra = _number(parameters, "lra", 11.0)
    if not -24.0 <= target_lufs <= -14.0 or not 1.0 <= lra <= 20.0:
        raise rescue_error("loudness parameters exceed rescue policy bounds", RESCUE_POLICY_VIOLATION)
    normalize_audio(input_path, target_lufs=target_lufs, lra=lra, output_path=output_path)


def _run_exposure(input_path: str, output_path: str, parameters: Mapping[str, Any]) -> None:
    level = _number(parameters, "level", 0.0)
    if not -0.08 <= level <= 0.08:
        raise rescue_error("exposure level must be within [-0.08, 0.08]", RESCUE_POLICY_VIOLATION)
    apply_filter(input_path, "brightness", {"level": level}, output_path=output_path)


def _run_normalize(input_path: str, output_path: str, parameters: Mapping[str, Any]) -> None:
    normalize(input_path, output_path)


OPERATION_REGISTRY: dict[RepairType, OperationAdapter] = {
    RepairType.ROTATION: OperationAdapter(frozenset({"angle"}), _run_rotation),
    RepairType.CONTAINER_TIMESTAMPS: OperationAdapter(frozenset(), _run_normalize),
    RepairType.METADATA: OperationAdapter(frozenset(), _run_normalize),
    RepairType.AUDIO_LOUDNESS: OperationAdapter(frozenset({"target_lufs", "lra"}), _run_loudness),
    RepairType.EXPOSURE: OperationAdapter(frozenset({"level"}), _run_exposure),
}


def execute_repair(
    repair: Repair,
    input_path: str,
    output_path: str,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> OperationResult:
    """Execute one safe repair through its exact bounded adapter."""

    if repair.disposition is not Disposition.SAFE_REPAIR or not repair.promotable:
        raise rescue_error(f"repair {repair.id} is not executable", RESCUE_POLICY_VIOLATION)
    adapter = OPERATION_REGISTRY.get(repair.type)
    unknown = set(repair.parameters).difference(adapter.allowed_parameters) if adapter else set(repair.parameters)
    if adapter is None or unknown:
        raise rescue_error(
            f"repair {repair.id} has no closed adapter or contains unknown parameters",
            RESCUE_POLICY_VIOLATION,
        )

    started = time.monotonic()
    if on_progress is not None:
        on_progress(0.0)
    adapter.run(input_path, output_path, repair.parameters)
    if on_progress is not None:
        on_progress(100.0)
    return OperationResult(
        operation=repair.type.value,
        repair_id=repair.id,
        output_path=output_path,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        sha256=_sha256(output_path),
    )


def _copy_result(operation: str, source: str, destination: str) -> OperationResult:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path == destination_path:
        raise rescue_error("rescue output may not overwrite its input", UNSAFE_RESCUE_OUTPUT)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    shutil.copy2(source_path, destination_path)
    return OperationResult(
        operation=operation,
        output_path=str(destination_path),
        elapsed_ms=round((time.monotonic() - started) * 1000),
        sha256=_sha256(destination_path),
    )


def make_master(source: str, approved_outputs: Sequence[str], master_path: str) -> OperationResult:
    """Copy the final approved intermediate, or the untouched source, as master."""

    final_input = approved_outputs[-1] if approved_outputs else source
    return _copy_result("make_master", final_input, master_path)


def make_universal_copy(
    master: str,
    share_path: str,
    on_progress: Callable[[float], None] | None = None,
) -> OperationResult:
    """Always produce the required H.264/AAC yuv420p sharing artifact."""

    if Path(master).resolve() == Path(share_path).resolve():
        raise rescue_error("sharing copy may not overwrite the master", UNSAFE_RESCUE_OUTPUT)
    Path(share_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    convert(master, format="mp4", quality="high", output_path=share_path, on_progress=on_progress)
    return OperationResult(
        operation="make_universal_copy",
        output_path=share_path,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        sha256=_sha256(share_path),
    )
