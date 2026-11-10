# Architecture Audit — Deepening Candidates

Generated using the `improve-codebase-architecture` discipline (depth, seam, adapter, deletion test).

## Method

For each candidate, we apply the **deletion test**: *"Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep."*

A module is **shallow** when its interface is nearly as complex as its implementation. A module is **deep** when a lot of behavior sits behind a small interface.

---

## Candidate 1: CLI Command Dispatch — Extract a `CommandRunner` Seam

**Files:** `cli/handlers_core.py`, `cli/handlers_media.py`, `cli/handlers_advanced.py`, `cli/handlers_audio.py`, `cli/handlers_ai.py`, `cli/handlers_effects.py`, `cli/handlers_hyperframes.py`, `cli/handlers_composition.py`

**Problem:**
Every handler is a giant `if/elif` chain where each branch repeats the exact same 4-step cycle:
1. Lazy-import the engine function
2. Call it through `_with_spinner(message, engine_fn, ...)`
3. Format output (`output_json(result)` vs `_format_*_text(result)`)
4. `return True`

The interface (`args`, `use_json`) is nearly as complex as the implementation. There is no seam between "what command to run" and "how to run it." Deleting any handler would just move its branches into the caller — no complexity is hidden.

**Solution:**
Extract a `CommandRunner` class that owns the dispatch cycle. Each command registers a `(engine_fn, spinner_message, formatter)` tuple. The runner handles lazy imports, spinner wrapping, and output formatting.

Custom formatters (rich tables for `detect-scenes`, `export-frames`, `compare-quality`, etc.) move to `cli/formatters/` as small adapters.

**Benefits:**
- **Locality:** Change the dispatch cycle once (e.g., add progress bars), fixed everywhere.
- **Leverage:** New commands only specify engine_fn + message + formatter — ~5 lines instead of ~15.
- **Testability:** Test the runner cycle with a fake engine; test formatters with fake data.

**Risk:** Low. Pure refactor, no behavior change. CLI tests already exercise these paths.

---

## Candidate 2: `audio_preset` — Separate Data from Logic

**Files:** `audio_engine/synthesis.py`

**Problem:**
`audio_preset` is 192 lines. ~160 of those lines are a static `dict` of preset configurations (waveform, frequency, duration, volume, effects). The interface is small (`preset`, `output`, `pitch`, `duration`, `intensity`) but the implementation IS the data table. This is shallow — deleting the function just moves the dict.

**Solution:**
Move the presets dictionary to `audio_engine/presets.py` (or a JSON data file). `audio_preset` becomes:

```python
def audio_preset(preset, output, pitch="mid", duration=None, intensity=0.5):
    config = _PRESETS[preset].copy()
    config["frequency"] *= _PITCH_MULT[pitch]
    if duration:
        config["duration"] = duration
    # Apply intensity override where relevant
    return audio_synthesize(output=output, **config)
```

~15 lines. The data table lives in its own file, versioned independently.

**Benefits:**
- **Locality:** Preset changes (new presets, tuning values) concentrate in one file.
- **Leverage:** Presets can be loaded, validated, and listed without importing the synthesis engine.
- **Testability:** Test preset lookup and override logic without generating audio.

**Risk:** Very low. The function delegates to `audio_synthesize` already; we're just moving data.

---

## Candidate 3: `analyze_video` — Extract Analysis Runner Helper

**Files:** `ai_engine/__init__.py`

**Problem:**
`analyze_video` is a 242-line orchestrator that runs 7 independent analyses. Each analysis is wrapped in an identical `try/except Exception` pattern with error appending. The function also inlines URL resolution, path validation (blocked system directories), and result assembly.

The deletion test is mixed: deleting it would scatter the 7 analysis calls across callers, BUT the error-handling pattern is duplicated 7 times and could be centralized.

**Solution:**
Extract `_run_analysis(name, fn, *args, **kwargs) → Any | None` that wraps the try/except/logging pattern and returns the result or `None` on failure. Extract the blocked-prefix path validation to `validation.py` (it already exists as a concept).

`analyze_video` becomes ~80 lines of pure orchestration:
1. Resolve video source
2. Run each analysis via `_run_analysis`
3. Assemble the result dict
4. Clean up temp dir in `finally`

**Benefits:**
- **Locality:** Error handling logic lives in one place. Change "how we handle analysis failures" once.
- **Leverage:** New analysis sections are one-liners: `result = _run_analysis("colors", _effects.extract_colors, path)`.
- **Testability:** Test orchestration with mocked `_run_analysis`; test real analyses independently.

**Risk:** Low. The try/except pattern is uniform; extracting it is mechanical.

---

## Candidate 4: `merge` — Separate Normalization from Merge Strategy

**Files:** `engine_merge.py`

**Problem:**
`merge` is 138 lines that mixes three concerns:
1. Single-clip fast path (copy/remux)
2. Multi-clip normalization (resize, pad, rotate, re-encode) — ~40 lines inline
3. Merge strategy selection (concat vs transitions) and execution

The normalization logic is complex (scale, pad, transpose for rotation, re-encode with fixed params) and lives inline inside the merge function. Deleting `merge` would scatter all three concerns.

**Solution:**
Extract `_normalize_clips(clips, infos, target_w, target_h, tmpdir) → list[str]` that handles the normalization loop. `merge` becomes:
1. Validate inputs
2. Probe all clips
3. Decide if normalization needed
4. `working_clips = _normalize_clips(...) if needed else clips`
5. Pick strategy (concat or transitions) and execute
6. Probe output, return result

**Benefits:**
- **Locality:** Normalization bugs (e.g., wrong rotation handling) fix in one place.
- **Leverage:** Normalization can be reused by other engines that need uniform clips.
- **Testability:** Test normalization with mocked FFmpeg; test merge strategy selection independently.

**Risk:** Low. The normalization block is already a self-contained loop with clear inputs/outputs.

---

## Candidate 5: `add_audio` — Extract Filter Builder

**Files:** `engine_audio_ops.py`

**Problem:**
`add_audio` is 123 lines with two branches (mix vs replace) that both build identical audio filters (`volume`, `fade_in`, `fade_out`) and construct FFmpeg args. The filter-building logic repeats in both branches with only minor differences (one uses `-filter_complex`, the other uses `-af`).

**Solution:**
Extract `_build_audio_filters(volume, fade_in, fade_out, duration) → list[str]` and `_build_add_audio_args(video, audio, filters, mix, start_time, output) → list[str]`. The main function becomes:
1. Validate inputs
2. Probe video
3. `filters = _build_audio_filters(...)`
4. Branch on `mix` and `source_has_audio`
5. Build args via helper, run FFmpeg
6. Return result

**Benefits:**
- **Locality:** Filter construction bugs (e.g., wrong fade timing) fix once.
- **Leverage:** Filter builder reusable for other audio operations (normalize, spatial, etc.).
- **Testability:** Test filter strings without running FFmpeg.

**Risk:** Very low. Pure extraction of duplicated logic.

---

## Quick Wins (Lower Leverage, Easy)

| Function | Lines | Fix | Effort |
|----------|-------|-----|--------|
| `effects_engine/text.py:text_animated` | 108 | Extract `_build_alpha_expr(animation, start, duration)` and `_build_drawtext_filter(...)` | Small |
| `audio_engine/synthesis.py:audio_synthesize` | 107 | Extract `_apply_effects(samples, effects, duration, sample_rate)` | Small |
| `engine_speed.py:speed` | 103 | Already simple; length is mostly docstring + validation | Skip |
| `effects_engine/layout.py:layout_grid` | 103 | Grid math is inherently verbose; may not deepen well | Skip |
| `engine_storyboard.py:storyboard` | 93 | Frame extraction math + FFmpeg call; borderline | Skip |

---

## Priority Ranking

| Rank | Candidate | Leverage | Risk | Effort |
|------|-----------|----------|------|--------|
| 1 | `audio_preset` data extraction | High | Very Low | 30 min |
| 2 | `add_audio` filter builder | High | Very Low | 30 min |
| 3 | `merge` normalization extraction | High | Low | 45 min |
| 4 | `analyze_video` analysis runner | Medium | Low | 45 min |
| 5 | CLI `CommandRunner` seam | Very High | Low | 2-3 hrs |

---

## What We Won't Touch

The following functions exceed 80 lines but are **already deep** or **not worth the churn**:

- **`server_tools_*.py` tool handlers** (~40 functions, 80-120 lines each): These are thin wrappers by design (ADR-0003). They validate inputs and delegate. Splitting them would create *more* files with *less* depth.
- **`cli/parser/*.py:add_parsers`** (~10 functions, 80-120 lines each): These are declarative argparse configurations. The length is `add_argument()` calls — extracting helpers would not improve readability.
- **`engine_hls.py:hls_segment`** (91 lines): HLS segment logic is inherently complex (variant playlists, iframe playlists, encryption). The interface is already small relative to the domain complexity.
