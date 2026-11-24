"""Song-relative slots and film-relative frames. Never accumulate rounded durations."""

import itertools
import math
import re
import warnings
from array import array
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..errors import MCPVideoError

FINE_GRID_384 = 384


def _ratio(value):
    return Fraction(str(value))


def round_half_up(value):
    """Nearest integer; exact half ties round away from zero."""
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
            if re.fullmatch(r"[1-9]\d*:[1-9]\d*:\d+", text):
                bar, beat, sub = map(int, text.split(":"))
                if beat > self.beats_per_bar:
                    raise ValueError("Beat exceeds the meter")
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
        return float(frame / _ratio(self.fps))

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
        return float(_ratio(self.offset_s) + slot * self._unit)

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


def validate_edit_points(points, grid, tolerance_ms=2.0):
    if not math.isfinite(tolerance_ms) or tolerance_ms < 0:
        raise ValueError("Tolerance must be finite and nonnegative")
    rows = []
    for point in points:
        actual = grid._parse(point)
        slot, snapped, residual = grid.nearest(actual)
        rows.append(
            dict(
                time=float(actual),
                slot=slot,
                snapped_s=snapped,
                residual_ms=residual,
                passed=abs(residual) <= tolerance_ms,
            )
        )
    return dict(grid=grid.receipt(), points=rows, passed=all(row["passed"] for row in rows))


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
        stdout_limit=960000,
    )
    if result.returncode:
        raise ValueError("Could not decode music bed")
    samples = array("h", result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    energy = [sum(map(abs, samples[pos : pos + 80])) for pos in range(0, len(samples), 80)]
    onsets = [max(0, right - left) for left, right in itertools.pairwise(energy)]
    scores = [
        (sum(first * second for first, second in zip(onsets, onsets[lag:], strict=False)), lag)
        for lag in range(32, 101)
    ]
    score, lag = max(scores, key=lambda pair: pair[0])
    if not score:
        raise ValueError("No repeating onsets found")
    return 6000.0 / lag
