"""Song-relative slots and film-relative frames. Never accumulate rounded durations."""

import itertools
import math
import re
import warnings
from array import array
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import TypedDict

from ..errors import MCPVideoError

FINE_GRID_384 = 384


def _ratio(value):
    return Fraction(str(value))


def round_half_up(value):
    """Nearest integer; exact half ties round away from zero."""
    if isinstance(value, bool):
        raise ValueError("Expected a numeric position")
    return math.floor(value + Fraction(1, 2)) if value >= 0 else -round_half_up(-value)


@dataclass(frozen=True)
class MusicalGrid:
    bpm: float
    fps: float = 30.0
    offset_s: float = 0.0
    steps_per_bar: int = 64
    beats_per_bar: int = 4
    floor_ms: float = 5.0

    def __post_init__(self):
        for value in (self.steps_per_bar, self.beats_per_bar):
            if type(value) is not int or value < 1:
                raise ValueError("Bar divisions must be positive integers")
        if self.steps_per_bar % self.beats_per_bar:
            raise ValueError("Grid must contain whole beats")
        if min(_ratio(self.fps), _ratio(self.bpm)) <= 0 or _ratio(self.floor_ms) < 0:
            raise ValueError("Tempo and frame rate must be positive; floor must be nonnegative")
        _ratio(self.offset_s)
        if self.step_ms < self.floor_ms:
            warnings.warn("Musical grid step is below the configured timing floor", UserWarning, stacklevel=2)

    @property
    def _unit(self):
        return 60 * self.beats_per_bar / _ratio(self.bpm) / self.steps_per_bar

    @property
    def step_ms(self):
        return float(1000 * self._unit)

    def validate_note_values(self, note_values):
        for note in note_values:
            if type(note) is not int or note <= 0:
                raise ValueError("Note denominators must be positive integers")
            remainder = self.steps_per_bar % note
            if remainder:
                raise MCPVideoError(
                    f"Note value {note:d} leaves remainder {remainder:d}; try {math.lcm(note, self.steps_per_bar):d} steps",
                    error_type="validation_error",
                    code="invalid_grid_resolution",
                )

    def _parse(self, value):
        if isinstance(value, str):
            text = value.strip()
            if text.count(":") == 2 and not text.startswith("tc:"):
                if not re.fullmatch(r"[1-9]\d*:[1-9]\d*:\d+", text):
                    raise ValueError("Invalid bar:beat:sub coordinate")
                bar, beat, sub = map(int, text.split(":"))
                if beat > self.beats_per_bar or sub >= self.steps_per_bar // self.beats_per_bar:
                    raise ValueError("Beat or subdivision exceeds the meter")
                slot = ((bar - 1) * self.beats_per_bar + beat - 1) * (self.steps_per_bar // self.beats_per_bar) + sub
                return _ratio(self.offset_s) + slot * self._unit
            if ":" in text:
                parts = text.removeprefix("tc:").split(":")
                if len(parts) not in (2, 3):
                    raise ValueError("Invalid timecode")
                return sum(int(part) * 60**power for power, part in enumerate(reversed(parts[:-1]), 1)) + _ratio(
                    parts[-1]
                )
        return _ratio(value)

    def parse_time(self, value):
        return float(self._parse(value))

    def frame_to_seconds(self, frame):
        return float(_ratio(frame) / _ratio(self.fps))

    def time_to_frame(self, value):
        return round_half_up(self._parse(value) * _ratio(self.fps))

    def cut(self, value):
        nominal = self._parse(value)
        frame = round_half_up(nominal * _ratio(self.fps))
        final = frame / _ratio(self.fps)
        return dict(
            frame=frame,
            nominal_time=float(nominal),
            final_time=float(final),
            residual_ms=float(1000 * (final - nominal)),
        )

    def slot_time(self, slot):
        return float(_ratio(self.offset_s) + _ratio(slot) * self._unit)

    def nearest(self, seconds, *, duration=False):
        origin = 0 if duration else _ratio(self.offset_s)
        actual = _ratio(seconds)
        slot = round_half_up((actual - origin) / self._unit)
        snapped = origin + slot * self._unit
        return slot, float(snapped), float((actual - snapped) * 1000)

    def receipt(self):
        return dict(
            bpm=self.bpm,
            fps=self.fps,
            offset_s=self.offset_s,
            steps_per_bar=self.steps_per_bar,
            beats_per_bar=self.beats_per_bar,
            step_ms=self.step_ms,
        )


def resolve_timeline_times(data):
    from copy import deepcopy

    data = deepcopy(data)
    options = data.get(
        "grid", {key: data[key] for key in ("bpm", "fps", "offset_s", "steps_per_bar", "beats_per_bar") if key in data}
    )
    if not isinstance(options, dict):
        raise ValueError("Expected grid settings")
    try:
        grid = MusicalGrid(**options)
    except TypeError as exc:
        raise ValueError("Invalid grid settings") from exc
    relative = replace(grid, offset_s=0, floor_ms=0)

    def _require_finite(value):
        if value is None:
            return
        if isinstance(value, bool):
            raise ValueError("Expected finite numeric timeline value")
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                raise ValueError("Expected finite numeric timeline value")
        elif isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError as exc:
                raise ValueError("Expected finite numeric timeline value") from exc
            if not math.isfinite(parsed):
                raise ValueError("Expected finite numeric timeline value")

    def resolve(item):
        if isinstance(item, dict):
            for key in ("start", "duration", "trim_start", "trim_end", "fade_in", "fade_out"):
                value = item.get(key)
                if value is None:
                    continue
                if isinstance(value, bool):
                    raise ValueError("Expected numeric timeline time")
                if isinstance(value, str) and ":" in value:
                    item[key] = (grid if key == "start" else relative).parse_time(value)
                    continue
                _require_finite(value)
            for key in ("volume", "opacity", "x", "y", "width", "height", "after_clip"):
                _require_finite(item.get(key))
            pos = item.get("position")
            if isinstance(pos, dict):
                for coord in pos.values():
                    _require_finite(coord)

    resolve(data)
    tracks = data.get("tracks", [])
    for track in tracks if isinstance(tracks, list) else []:
        if isinstance(track, dict):
            for group in ("clips", "transitions", "elements", "images"):
                items = track.get(group)
                if isinstance(items, list):
                    for item in items:
                        resolve(item)
    return data


class PointReceipt(TypedDict):
    time: float
    slot: int
    snapped_s: float
    residual_ms: float
    passed: bool


class ValidationReceipt(TypedDict):
    grid: dict
    points: list[PointReceipt]
    passed: bool


def validate_edit_points(points, grid, tolerance_ms=2.0) -> ValidationReceipt:
    if isinstance(tolerance_ms, bool) or not math.isfinite(tolerance_ms) or tolerance_ms < 0:
        raise ValueError("Tolerance must be finite and nonnegative")
    rows: list[PointReceipt] = []
    for point in points:
        actual = grid._parse(point)
        slot, snapped, residual = grid.nearest(actual)
        rows.append(
            PointReceipt(
                time=float(actual),
                slot=slot,
                snapped_s=snapped,
                residual_ms=residual,
                passed=abs(residual) <= tolerance_ms,
            )
        )
    return ValidationReceipt(grid=grid.receipt(), points=rows, passed=all(row["passed"] for row in rows))


def estimate_bpm_from_audio(audio_path):
    """Estimate 60-188 BPM from at most one minute of 8 kHz mono audio."""
    import sys
    from ..bounded_process import run_bounded
    from ..engine_runtime_utils import _ffmpeg
    from ..ffmpeg_helpers import _validate_input_path

    path = _validate_input_path(str(Path(audio_path)))
    result = run_bounded(
        [
            _ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            path,
            "-t",
            "60",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "pipe:1",
        ],
        timeout=45,
        text=False,
        stdout_limit=1048576,
    )
    if result.returncode:
        raise ValueError("Could not decode music bed")
    samples = array("h", result.stdout[:960000])
    if sys.byteorder != "little":
        samples.byteswap()
    energy = [sum(map(abs, samples[pos : pos + 80])) for pos in range(0, len(samples), 80)]
    onsets = [max(0, right - left) for left, right in itertools.pairwise(energy)]
    n = len(onsets)
    scores = [
        (
            sum(first * second for first, second in zip(onsets, onsets[lag:], strict=False)) / (n - lag),
            lag,
        )
        for lag in range(32, 101)
        if n > lag
    ]
    if not scores:
        raise ValueError("No repeating onsets found")
    score, lag = max(scores, key=lambda pair: pair[0])
    if not score:
        raise ValueError("No repeating onsets found")
    return 6000.0 / lag
