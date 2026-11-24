"""Transient clearance and per-event placement precedence."""

from bisect import bisect_left, bisect_right
from pathlib import Path

from ..errors import MCPVideoError
from .onsets import _movement_bounds, _nonnegative, _validate_confidence, detect_onsets, pocket_lock


def _clearance_zones(times: list[float], clearance: float) -> list[tuple[float, float]]:
    zones: list[tuple[float, float]] = []
    for time in times:
        start, end = time - clearance, time + clearance
        if zones and start < zones[-1][1]:
            zones[-1] = (zones[-1][0], end)
        else:
            zones.append((start, end))
    return zones


def _escape(original, zone, max_shift_ms, prefer):
    lower, upper = _movement_bounds(original, max_shift_ms)
    candidates = [
        (target, direction)
        for target, direction in zip(zone, ("early", "late"), strict=True)
        if lower <= target <= upper
    ]
    if not candidates:
        return original
    return min(candidates, key=lambda option: (option[1] != prefer, round(abs(option[0] - original), 12), option[0]))[0]


def nudge_off_transients(
    events, transients, *, clearance_ms=12.0, max_shift_ms=15.0, prefer="late", bands=("kick", "snare")
):
    """Clear all selected transients. Prefer the requested side when feasible, then try the other."""
    if prefer not in ("late", "early", "nearest"):
        raise MCPVideoError("prefer must be late, early, or nearest", code="invalid_parameter")
    clearance = _nonnegative(clearance_ms, "clearance_ms") / 1000
    _nonnegative(max_shift_ms, "max_shift_ms")
    selected = set(bands)
    selected_times = set()
    for onset in transients:
        _validate_confidence(onset.confidence)
        if onset.band in selected:
            selected_times.add(_nonnegative(onset.time_s, "onset time_s"))
    times = sorted(selected_times)
    zones = _clearance_zones(times, clearance)
    starts = [start for start, _ in zones]
    placed, decisions, unresolved = [], [], []
    for index, event in enumerate(events):
        original = _nonnegative(event["time_s"], "event time_s")
        zone_index = bisect_left(starts, original) - 1
        final, triggering, remaining = original, None, []
        if zone_index >= 0 and original < zones[zone_index][1]:
            overlaps = times[bisect_right(times, original - clearance) : bisect_left(times, original + clearance)]
            if overlaps:
                triggering = min(overlaps, key=lambda time: (abs(time - original), time))
                if not event.get("fixed", False):
                    final = _escape(original, zones[zone_index], max_shift_ms, prefer)
                if final == original:
                    remaining = overlaps
                    unresolved.append({"event_index": index, "onset_times_s": remaining})
        placed.append(dict(event, time_s=final))
        decisions.append(
            {
                "original_time_s": original,
                "final_time_s": final,
                "triggering_onset_s": triggering,
                "shift_ms": (final - original) * 1000,
                "moved": final != original,
                "unresolved_overlaps": remaining,
            }
        )
    return placed, {"events": decisions, "unresolved_overlaps": unresolved}


def place_events_with_stem(
    events,
    stem_or_onsets,
    *,
    band="hat",
    max_window_ms=25.0,
    min_confidence=0.35,
    fine_grid_step_ms=None,
    clearance_ms=12.0,
    max_shift_ms=15.0,
    prefer="late",
    bands=("kick", "snare"),
):
    """Apply pocket lock first, then masking, for events in mode ``both`` (the default).

    Modes ``pocket_lock`` and ``avoid_masking`` opt into one pass only. Fixed
    events never move; those assigned masking are still checked for overlaps.
    Each pass has its own movement budget, relative to its starting position.
    """
    onsets = detect_onsets(stem_or_onsets) if isinstance(stem_or_onsets, (str, Path)) else list(stem_or_onsets)
    placed = [dict(event) for event in events]
    decisions = []
    pockets, masks = [], []
    for index, event in enumerate(placed):
        mode = event.get("mode", "both")
        if mode not in ("pocket_lock", "avoid_masking", "both"):
            raise MCPVideoError("Unknown audio placement mode", code="invalid_parameter")
        time = _nonnegative(event["time_s"], "event time_s")
        decisions.append({"original_time_s": time, "mode": mode, "pocket_lock": None, "masking": None})
        if mode != "avoid_masking":
            pockets.append(index)
        if mode != "pocket_lock":
            masks.append(index)
    snapped, pocket = pocket_lock(
        (placed[index] for index in pockets),
        onsets,
        band=band,
        max_window_ms=max_window_ms,
        min_confidence=min_confidence,
        fine_grid_step_ms=fine_grid_step_ms,
    )
    for index, event, decision in zip(pockets, snapped, pocket["events"], strict=True):
        placed[index], decisions[index]["pocket_lock"] = event, decision
    cleared, masking = nudge_off_transients(
        (placed[index] for index in masks),
        onsets,
        clearance_ms=clearance_ms,
        max_shift_ms=max_shift_ms,
        prefer=prefer,
        bands=bands,
    )
    for index, event, decision in zip(masks, cleared, masking["events"], strict=True):
        placed[index], decisions[index]["masking"] = event, decision
    for event, decision in zip(placed, decisions, strict=True):
        decision.update(final_time_s=event["time_s"], moved=event["time_s"] != decision["original_time_s"])
    return placed, {
        "events": decisions,
        "unmatched_events": [pockets[index] for index in pocket["unmatched_events"]],
        "unresolved_overlaps": [
            dict(item, event_index=masks[item["event_index"]]) for item in masking["unresolved_overlaps"]
        ],
    }
