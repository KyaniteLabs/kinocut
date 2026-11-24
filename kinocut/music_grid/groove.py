"""Map only timestamp fields, never retain the input records."""

from collections.abc import Mapping
from datetime import datetime, UTC
import math
import itertools
from typing import TypedDict


class GrooveReceipt(TypedDict):
    grid: dict
    time_scale: float
    events: list[dict[str, float]]
    collisions: list[tuple[int, int]]


def _timestamp(value):
    try:
        if isinstance(value, Mapping):
            for field in ("timestamp_ms", "time_ms", "timestamp_s", "time_s", "timestamp", "time"):
                if field in value:
                    value = value[field]
                    if isinstance(value, bool):
                        raise ValueError
                    if field.endswith("_ms"):
                        value = float(value) / 1000
                    break
            else:
                raise ValueError
        if isinstance(value, str):
            value = value.strip()
            if value.endswith("ms"):
                value = float(value[:-2]) / 1000
            elif "T" in value or " " in value:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                value = (instant if instant.tzinfo else instant.replace(tzinfo=UTC)).timestamp()
            else:
                value = value.removesuffix("s")
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError
        return float(value)
    except (ValueError, TypeError, OverflowError, OSError):
        raise ValueError("Invalid source timestamp") from None


def quantize_real_timestamps(
    timestamps, grid, *, quantize_strength=100.0, strength_curve=None, target_duration_s=None, start_time_s=0.0
) -> GrooveReceipt:
    source = [_timestamp(record) for record in timestamps]
    if any(a > b for a, b in itertools.pairwise(source)):
        raise ValueError("Source timestamps must be non-decreasing")
    if (
        any(isinstance(value, bool) for value in (start_time_s, quantize_strength, target_duration_s))
        or not math.isfinite(start_time_s)
        or not 0 <= quantize_strength <= 100
    ):
        raise ValueError("Invalid timeline start or strength")
    span = source[-1] - source[0] if source else 0.0
    if target_duration_s is not None and (not math.isfinite(target_duration_s) or target_duration_s < 0):
        raise ValueError("Invalid target duration")
    scale = target_duration_s / span if span and target_duration_s is not None else 1.0
    events, collisions = [], []
    for index, timestamp in enumerate(source):
        elapsed = (timestamp - source[0]) * scale
        mapped = start_time_s + elapsed
        strength = (
            quantize_strength
            if strength_curve is None
            else strength_curve.value_at(elapsed * grid.bpm / (60 * grid.beats_per_bar))
        )
        if isinstance(strength, bool) or not 0 <= strength <= 100:
            raise ValueError("Strength must be between 0 and 100")
        _, snapped, _ = grid.nearest(mapped)
        final = snapped if strength == 100 else mapped + (snapped - mapped) * strength / 100
        if events and final <= events[-1]["final_time"]:
            final = events[-1]["final_time"]
            collisions.append((index - 1, index))
        events.append(
            dict(
                source_time=timestamp,
                mapped_time=mapped,
                final_time=final,
                strength=strength,
                residual_ms=(final - snapped) * 1000,
            )
        )
    return GrooveReceipt(grid=grid.receipt(), time_scale=scale, events=events, collisions=collisions)
