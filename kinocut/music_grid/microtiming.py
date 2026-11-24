"""Apply expressive timing after slot placement, before rendering."""

from dataclasses import dataclass
import math


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class TimingCurve:
    start_value: float
    end_value: float
    duration_bars: float
    shape: str = "linear"
    step_bars: float = 2.0

    def __post_init__(self):
        if not all(map(_finite, (self.start_value, self.end_value, self.duration_bars, self.step_bars))):
            raise ValueError("Curve values must be finite")
        if self.shape not in ("linear", "stepped") or min(self.duration_bars, self.step_bars) <= 0:
            raise ValueError("Invalid curve shape or length")

    def value_at(self, bars):
        if not _finite(bars):
            raise ValueError("Invalid curve position")
        if self.shape == "linear":
            progress = bars / self.duration_bars
        else:
            intervals = math.ceil(self.duration_bars / self.step_bars) - 1
            progress = math.floor(bars / self.step_bars) / intervals if intervals else int(bars >= self.duration_bars)
        return self.start_value + (self.end_value - self.start_value) * max(0, min(1, progress))


@dataclass(frozen=True)
class MicrotimingConfig:
    swing_pct: float = 50.0
    swing_subdivision: int = 16
    offset_ms: float = 0.0
    accent_pattern: tuple[float, ...] | None = None
    curve: TimingCurve | None = None
    swing_curve: TimingCurve | None = None

    def __post_init__(self):
        swings = [self.swing_pct]
        if self.swing_curve is not None:
            swings.extend((self.swing_curve.start_value, self.swing_curve.end_value))
        if not all(_finite(value) and 0 < value < 100 for value in swings) or not _finite(self.offset_ms):
            raise ValueError("Invalid swing or offset")
        if type(self.swing_subdivision) is not int or self.swing_subdivision < 1:
            raise ValueError("Invalid swing subdivision")
        if self.accent_pattern is not None and (not self.accent_pattern or not all(map(_finite, self.accent_pattern))):
            raise ValueError("Accent pattern must contain finite gains")

    def apply(self, nominal_time, grid, *, section_start_bar=1, gain_db=0.0):
        if not _finite(section_start_bar) or not _finite(gain_db):
            raise ValueError("Invalid section origin or gain")
        slot, _, residual = grid.nearest(nominal_time)
        local = slot % grid.steps_per_bar
        offset = (
            self.offset_ms
            if self.curve is None
            else self.curve.value_at(slot / grid.steps_per_bar - section_start_bar + 1)
        )
        swing = 0.0
        if self.swing_curve is not None or self.swing_pct != 50:
            grid.validate_note_values([self.swing_subdivision])
            width = grid.steps_per_bar // self.swing_subdivision
            position = slot + residual / grid.step_ms
            pair = math.floor(position / (2 * width)) * 2 * width
            phase = position - pair
            strength = (
                self.swing_pct
                if self.swing_curve is None
                else self.swing_curve.value_at(pair / grid.steps_per_bar - section_start_bar + 1)
            )
            swing = (strength - 50) / 50 * min(phase, 2 * width - phase) * grid.step_ms
        accent = 0.0 if self.accent_pattern is None else self.accent_pattern[local % len(self.accent_pattern)]
        delta = offset + swing
        return dict(
            nominal_time=nominal_time,
            final_time=nominal_time if not delta else nominal_time + delta / 1000,
            offset_ms=offset,
            swing_ms=swing,
            accent_db=accent,
            gain_db=gain_db + accent,
            residual_ms=residual + delta,
        )
