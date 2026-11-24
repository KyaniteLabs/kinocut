"""One phrase, one clock for sound and picture."""

from .microtiming import MicrotimingConfig

_CELLS = {
    "straight": (4, (0, 1, 2, 3)),
    "tresillo": (8, (0, 3, 6)),
    "son_clave": (16, (0, 3, 6, 10, 12)),
    "push": (8, (3, 7)),
    "off_beat": (8, (1, 3, 5, 7)),
}


def _labels(values, count):
    if values is None or isinstance(values, str):
        return [values] * count
    labels = list(values)
    if len(labels) != count:
        raise ValueError("Provide one label per hit or one shared label")
    return labels


def place_rhythm_cell(cell, grid, *, phrase_bars=2, events=None, sfx=None, start_bar=1, microtiming=None):
    if any(type(value) is not int or value < 1 for value in (start_bar, phrase_bars)):
        raise ValueError("Phrase length and start bar must be positive integers")
    span = phrase_bars * grid.steps_per_bar
    if isinstance(cell, str):
        if cell not in _CELLS:
            raise ValueError("Unknown rhythm cell")
        division, pattern = _CELLS[cell]
        if any(step * span % division for step in pattern):
            raise ValueError("Cell does not fit this phrase resolution")
        slots = [step * span // division for step in pattern]
    else:
        slots = list(cell)
        if any(type(step) is not int or not 0 <= step < span for step in slots) or slots != sorted(set(slots)):
            raise ValueError("Custom steps must be increasing integers inside the phrase")
    picture, sound = [], []
    config = microtiming or MicrotimingConfig()
    for slot, image, effect in zip(slots, _labels(events, len(slots)), _labels(sfx, len(slots)), strict=False):
        absolute = (start_bar - 1) * grid.steps_per_bar + slot
        timing = config.apply(grid.slot_time(absolute), grid, section_start_bar=start_bar)
        picture.append(dict(slot=absolute, event=image, **timing))
        sound.append(dict(slot=absolute, event=effect, **timing))
    return dict(grid=grid.receipt(), picture_events=picture, sfx_events=sound)
