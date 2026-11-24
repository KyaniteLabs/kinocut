# Cutting on music

Use `kinocut.music_grid` for Python-authored timelines. BPM is explicit: an
ordinary `engine_edit.trim` call still uses seconds and its original timecode
parser. No MCP or CLI commands are added.

```python
from kinocut.engine_edit import trim
from kinocut.music_grid import MusicalGrid, validate_edit_points

grid = MusicalGrid(126, fps=30, offset_s=0.512)
cut = grid.cut("1:2:0")  # nominal_time, frame, final_time, residual_ms
result = trim("take.mp4", start="1:2:0", end="2:1:0", bpm=126, offset_s=0.512)
report = validate_edit_points([cut['final_time']], grid, tolerance_ms=3)
if not report['passed']:
    print(report['points'])
```

`bar:beat:sub` counts bars and beats from one, subdivisions from zero. A sub
is one grid step, not a fraction of the current beat: it may carry into the next
beat (`3:2:16` equals `3:3:0` on the default grid). With BPM set, unpadded
positive integer triples are musical. Use `tc:1:2:3` or `01:02:03` to force
clock time. Seconds and `MM:SS` are film-relative; the song offset only shifts
musical positions. For durations, `1:1:0` means zero elapsed time.

Grid arithmetic uses rational positions. Nearest slot and nearest frame both
round exact half ties away from zero. Each cut rounds its absolute endpoint
independently, never the previous cut plus a rounded interval. `fps` describes
the editing clock, not a frame-rate conversion. Cut residuals are **frame time
minus authored time**; validators show **authored time minus nearest slot**.
Trim warnings record the requested boundary frame and residual, not a measured
output timestamp. Stream copy still has the usual keyframe limitations.

## Fine slots and performance timing

`FINE_GRID_384` gives 384 steps per bar. `grid.validate_note_values([16,64,96,128])`
checks that the denominators divide the grid evenly. `grid.step_ms` is
`60000 / bpm * beats_per_bar / steps_per_bar`. The constructor warns below
`floor_ms` (5 by default); set it to zero to disable the warning. To estimate
rather than supply a tempo, call `estimate_bpm_from_audio(path)`: it decodes at
most 60 seconds with FFmpeg and correlates energy onsets. Silent or unpitched
timing without repeating onsets may yield no estimate; half/double-tempo
ambiguity is possible. It does not infer meter or downbeat.

```python
from kinocut.music_grid import MicrotimingConfig, TimingCurve, place_rhythm_cell

feel = MicrotimingConfig(swing_pct=56, offset_ms=15, accent_pattern=(2,0,0,0),
                         curve=TimingCurve(15, 0, 8, shape="stepped", step_bars=2))
phrase = place_rhythm_cell("tresillo", grid, phrase_bars=2, start_bar=5,
                           events=["flip_A", "flip_B", "flip_C"], sfx="click", microtiming=feel)
```

Apply `feel.apply(seconds, grid, section_start_bar=5, gain_db=-6)` to one
event or reuse it for a track or section. The curve replaces the millisecond
offset; the example holds 15, 10, 5, then 0 ms for two bars each. A linear curve
reaches its end at the section boundary. Swing delays the off subdivision by
`(swing_pct - 50)/100` times a pair's duration. Accents add dB per grid slot
and restart at each bar. Keep final times at audio precision; converting them
back to picture frames would discard fine offsets. The two cell output lists
share exactly the same final times. Built-ins stretch across one phrase:
`straight` (four hits), `tresillo`, `son_clave`, `push`, and `off_beat`.
Custom steps are literal zero-based offsets within the phrase, not fractions.

## Recorded groove and animation

`quantize_real_timestamps(records, grid, start_time_s=3, target_duration_s=8,
quantize_strength=50)` maps the first source timestamp to 3 s and the last to
11 s before pulling each halfway toward its nearest slot. Numeric values mean
seconds; `"150ms"`, `timestamp_ms`, or `time_ms` explicitly select milliseconds.
ISO timestamps use their stated zone (UTC if absent). Only timestamp fields are
read. A zero-span recording stays at the start with scale 1. A `strength_curve`
uses elapsed mapped bars. Descending source times are refused rather than
sorted. If varying strength would cross a prior event, placement holds at the
prior final time and reports both zero-based indices in `collisions`.

`lint_composition_keyframes(source, grid, tolerance_ms=2)` returns `passed` and
named `keyframes`. For build gates, exit nonzero if `passed` is false. Supply
HTML `data-start`/`data-duration`, standalone literal `gsap.to` tweens (duration
and optional delay), or CSS `animation-duration`, `animation-delay`, and
`animation-name` longhands with percentage stops. This is not a browser or a JS
interpreter. For computed timings, CSS shorthands or sequenced GSAP timelines,
provide resolved events: `[{"name":"dolly", "start":3, "ease":4, "end":5},
{"name":"logo.fadeout", "time":7.3}]`. All fields except `duration` describe
absolute seconds. `snap_duration_to_grid(1.8, grid)` returns `(60, 1.785714…,
14.285714…)`: duration snapping always ignores song offset.
