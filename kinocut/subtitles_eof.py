"""Shared end-of-file clamp utility for timed segment lists (Plan 01 Task 3).

A pure, FFmpeg-free helper reused by subtitle generation, burn-in, and ASR:
given a list of timed segments and the media's end position, it trims any
segment that overshoots the end, drops any segment that begins at or after the
end (a zero-length range would otherwise result), and leaves an exactly-ending
segment untouched.

Segments may be bare ``(start, end)`` pairs or mapping records
(``{"start": ..., "end": ..., ...}``); a mapping's non-time fields are preserved
on the result for real ASR/subtitle consumers. Each result segment is an
immutable :class:`ClampedSegment` — a read-only mapping exposing ``start``,
``end`` and the preserved fields both as attributes and via ``seg["start"]`` /
``seg.get("text")``.

The whole input is validated atomically before any transform, the caller's data
is never mutated (metadata is recursively snapshotted and frozen), and the
result's warnings are a closed :class:`ClampWarning` enum. Every invalid input —
bad container, segment, chronology, EOF, or hostile metadata (non-string keys,
unsupported/cyclic/non-finite values) — raises a stable ``invalid_eof_clamp``
error that never echoes the offending value.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from kinocut.errors import MCPVideoError

#: Stable error code for every invalid clamp input (never echoes the raw value).
_INVALID = "invalid_eof_clamp"

_EMPTY_FIELDS: Mapping[str, object] = MappingProxyType({})


class ClampWarning(StrEnum):
    """Closed set of bounded, structured warning codes (never prose/raw values)."""

    CLAMPED = "segment_clamped_to_eof"
    DROPPED = "segment_dropped_after_eof"


class ClampedSegment(Mapping[str, object]):
    """Immutable, read-only mapping view of one clamped segment.

    ``start`` and ``end`` plus any preserved metadata fields are reachable both
    as attributes (``seg.start``) and via mapping access (``seg["start"]``,
    ``seg.get("text")``). Instances are immutable and never share mutable state
    with the caller's input: the constructor recursively validates and freezes
    the supplied ``fields``, so direct construction is as safe as the factory.
    """

    __slots__ = ("_end", "_fields", "_start")

    def __init__(self, start: float, end: float, fields: Mapping[str, object] = _EMPTY_FIELDS) -> None:
        object.__setattr__(self, "_start", start)
        object.__setattr__(self, "_end", end)
        object.__setattr__(self, "_fields", _freeze_fields(fields))

    @property
    def start(self) -> float:
        return self._start

    @property
    def end(self) -> float:
        return self._end

    @property
    def fields(self) -> Mapping[str, object]:
        return self._fields

    def __getitem__(self, key: str) -> object:
        if key == "start":
            return self._start
        if key == "end":
            return self._end
        return self._fields[key]

    def __iter__(self) -> Iterator[str]:
        yield "start"
        yield "end"
        yield from self._fields

    def __len__(self) -> int:
        return 2 + len(self._fields)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ClampedSegment is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ClampedSegment is immutable")

    def __repr__(self) -> str:
        return f"ClampedSegment(start={self._start!r}, end={self._end!r}, fields={dict(self._fields)!r})"


@dataclass(frozen=True)
class EofClampResult:
    """Immutable result of clamping segments to an end-of-file boundary."""

    segments: tuple[ClampedSegment, ...]
    warnings: tuple[ClampWarning, ...]
    clamped: int
    dropped: int


def _error(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=_INVALID)


def _finite_number(value: object) -> float:
    """Coerce a real, finite number; reject booleans, non-numbers, inf, and nan."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error("time values must be real numbers")
    number = float(value)
    if not math.isfinite(number):
        raise _error("time values must be finite")
    return number


def _freeze_metadata(value: object, seen: frozenset[int]) -> object:
    """Recursively validate and snapshot JSON-like metadata into an immutable value.

    Mappings become read-only views and sequences become tuples, so neither the
    result nor the caller's input can be mutated through the other. Non-string
    keys, unsupported types, non-finite numbers, and cyclic references are all
    rejected with a stable ``invalid_eof_clamp`` error.
    """

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("metadata numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if id(value) in seen:
            raise _error("metadata must not contain cycles")
        nested = seen | {id(value)}
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("metadata keys must be strings")
            frozen[key] = _freeze_metadata(item, nested)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        if id(value) in seen:
            raise _error("metadata must not contain cycles")
        nested = seen | {id(value)}
        return tuple(_freeze_metadata(item, nested) for item in value)
    raise _error("unsupported metadata type")


def _freeze_fields(fields: object) -> Mapping[str, object]:
    """Validate ``fields`` is a string-keyed mapping and deep-freeze every value.

    Used by both the factory and the :class:`ClampedSegment` constructor so that
    no construction path can store the caller's mutable structure verbatim.
    """

    if not isinstance(fields, Mapping):
        raise _error("segment fields must be a mapping")
    frozen: dict[str, object] = {}
    for key, value in fields.items():
        if not isinstance(key, str):
            raise _error("metadata keys must be strings")
        if key in ("start", "end"):
            raise _error("metadata keys must not shadow start or end")
        frozen[key] = _freeze_metadata(value, frozenset())
    return MappingProxyType(frozen) if frozen else _EMPTY_FIELDS


def _validate_times(start: object, end: object) -> tuple[float, float]:
    """Validate a ``start``/``end`` pair: finite, non-negative, strictly ordered."""

    start_f = _finite_number(start)
    end_f = _finite_number(end)
    if start_f < 0.0:
        raise _error("segment start must be non-negative")
    if end_f <= start_f:
        raise _error("segment end must be greater than start")
    return start_f, end_f


def _validate_segment(segment: object) -> tuple[float, float, Mapping[str, object]]:
    """Validate one segment record; return ``(start, end, immutable_fields)``."""

    if isinstance(segment, Mapping):
        if "start" not in segment or "end" not in segment:
            raise _error("mapping segments must have start and end")
        for key in segment:
            if not isinstance(key, str):
                raise _error("segment keys must be strings")
        start, end = _validate_times(segment["start"], segment["end"])
        extras = {key: _freeze_metadata(segment[key], frozenset()) for key in segment if key not in ("start", "end")}
        fields: Mapping[str, object] = MappingProxyType(extras) if extras else _EMPTY_FIELDS
        return start, end, fields
    if isinstance(segment, (tuple, list)) and len(segment) == 2:
        start, end = _validate_times(segment[0], segment[1])
        return start, end, _EMPTY_FIELDS
    raise _error("each segment must be a (start, end) pair or mapping record")


def clamp_segments_to_eof(segments: object, eof_seconds: object) -> EofClampResult:
    """Clamp ``segments`` to ``[0, eof_seconds]``, dropping any that start at/after EOF.

    Each segment that overshoots ``eof_seconds`` has its end clamped (recording a
    :attr:`ClampWarning.CLAMPED`); a segment starting at or beyond ``eof_seconds``
    is dropped (:attr:`ClampWarning.DROPPED`); an exactly-ending segment is kept
    unchanged. Order is preserved, the caller's data is never mutated, and any
    invalid input raises a stable ``invalid_eof_clamp`` error.
    """

    # Validate the top-level container itself: a bare mapping/string/number is a
    # common ASR-shape mistake and must fail closed, not be iterated element-wise.
    if not isinstance(segments, (list, tuple)):
        raise _error("segments must be a list or tuple of segment records")

    eof = _finite_number(eof_seconds)
    if eof <= 0.0:
        raise _error("eof_seconds must be a positive, finite number")

    # Validate the entire input up front so a single bad segment fails the whole
    # call atomically (no partial result), and enforce cross-segment chronology.
    validated: list[tuple[float, float, Mapping[str, object]]] = []
    previous_end = 0.0
    for segment in segments:
        start, end, fields = _validate_segment(segment)
        if start < previous_end:
            raise _error("segments must be chronological and non-overlapping")
        previous_end = end
        validated.append((start, end, fields))

    kept: list[ClampedSegment] = []
    warnings: list[ClampWarning] = []
    clamped = 0
    dropped = 0
    for start, end, fields in validated:
        if start >= eof:
            dropped += 1
            warnings.append(ClampWarning.DROPPED)
            continue
        if end > eof:
            end = eof
            clamped += 1
            warnings.append(ClampWarning.CLAMPED)
        kept.append(ClampedSegment(start, end, fields))
    return EofClampResult(tuple(kept), tuple(warnings), clamped, dropped)
