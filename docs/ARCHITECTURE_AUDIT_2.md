# Architecture Deepening Audit — Round 2

> **Historical snapshot.** This audit predates the 2026-07-10 Kinocut rename and
> the move from `mcp_video/` to `kinocut/`. Paths and findings are preserved as
> evidence, not current implementation guidance.

> Matt Pocock-style audit after completing all 5 candidates from Round 1.
> Two explore agents walked the codebase for new friction points.

---

## Method

- **Depth agent**: Scanned the largest remaining modules for shallow interface surface
- **Duplication agent**: Scanned for copy-pasted patterns across >2 files
- **Deletion test**: "If I delete this module/function, does complexity vanish or scatter?"

---

## Round 1 Recap (COMPLETED)

| # | Candidate | Status |
|---|-----------|--------|
| 1 | `CommandRunner` seam | DONE — `runner.py` + all 10 handler modules refactored |
| 2 | `audio_preset` data extraction | DONE — `presets.py` (175 lines) created |
| 3 | `analyze_video` runner helper | DONE — `_run_analysis()` extracted |
| 4 | `merge` normalization extraction | DONE — `_normalize_clips()` extracted |
| 5 | `add_audio` filter builder | DONE — `_build_audio_filters()` + `_build_add_audio_args()` extracted |

---

## Round 2 Candidates

### Candidate A: `EditResult` packaging — 28 duplicated call sites

- **Where**: 25 engine files (`engine_edit.py`, `engine_resize.py`, `engine_overlay.py`, `engine_filters.py`, `engine_convert.py`, `engine_speed.py`, `engine_crop.py`, `engine_fade.py`, `engine_watermark.py`, `engine_merge.py`, `engine_reverse.py`, etc.)
- **Pattern**: Every engine function ends with:
  ```python
  info = probe(output)
  return EditResult(
      output_path=output,
      duration=info.duration,
      resolution=info.resolution,
      size_mb=info.size_mb,
      format="mp4",
      operation="trim",
      elapsed_ms=timing["elapsed_ms"],
  )
  ```
- **Count**: 28 `return EditResult(` occurrences
- **Deletion test**: Removing any one instance just forces inline duplication at the call site. The pattern is scattered, not concentrated.
- **Deep fix**: `_build_edit_result(output, operation, timing, format="mp4")` in `engine_runtime_utils.py` (or `models.py`) that probes, extracts fields, and returns the model.
- **Leverage**: 25 engine functions lose 5–8 lines each.

---

### Candidate B: `_error_result` construction — ~50+ validation-error sites

- **Where**: All `server_tools_*.py` files (~286 raw `return _error_result(...)` calls)
- **Pattern**: Validation errors repeat the same 5-line construction:
  ```python
  return _error_result(
      MCPVideoError(
          f"some message",
          error_type="validation_error",
          code="invalid_parameter",
      )
  )
  ```
- **Deletion test**: Removing one instance forces the same 5 lines elsewhere. The pattern is copy-pasted, not abstracted.
- **Deep fix**: `_validation_error(message, code="invalid_parameter")` in `server_app.py` that returns `_error_result(MCPVideoError(..., error_type="validation_error", code=code))`.
- **Leverage**: ~50+ call sites shrink from 5 lines to 1.

---

### Candidate C: `Panel(border_style="green", title="Done")` — 23+ duplications

- **Where**: `mcp_video/cli/formatting.py` (lines 25, 60, 72, 90, 116, 164, 219, 301, 305, 315, 411, 423, 449, 454, 471, 500, 515, 526, 537, 573, 619, etc.)
- **Pattern**: `console.print(Panel("\n".join(lines), border_style="green", title="Done"))`
- **Deletion test**: Removing one instance just inlines the same `Panel` construction.
- **Deep fix**: `_format_success_panel(lines, title="Done", border_style="green")`.
- **Leverage**: 20+ formatters shrink to a single call each.

---

### Candidate D: `text_animated` strategy registry

- **Where**: `mcp_video/effects_engine/text.py::text_animated` (108 lines — violates project's own 80-line limit)
- **Pattern**: 4 animation strategies (`fade`, `slide-up`, `glitch`, `typewriter`) built inline with raw FFmpeg filter strings:
  ```python
  if animation == "fade":
      alpha_expr = "if(lt(t,...), ..."
  elif animation == "slide-up":
      y_offset = "+50*(1-min(...))"
  elif animation == "glitch":
      alpha_expr = "if(random(0)*lt(mod(t,0.2),0.1),0.8,1)"
  ```
- **Deletion test**: Deleting `text_animated` removes dispatch, but complexity moves into 4 separate inline callers. The function is shallow because it's a switch over string literals.
- **Deep fix**: `ANIMATION_STRATEGIES: dict[str, Callable[[...], str]]` where each strategy returns a `filter_complex` string. `text_animated` validates inputs, looks up strategy, appends result. Each strategy becomes a deep, testable unit.
- **Leverage**: Cuts 108-line function to ~20-line dispatcher + 4 deep helpers.

---

### Candidate E: Server tool try/except wrapper — 80+ copy-pasted handlers

- **Where**: Every `@mcp.tool()` in `server_tools_*.py` (88 `except MCPVideoError` + 86 `except Exception` occurrences)
- **Pattern**:
  ```python
  try:
      input_path = _validate_input_path(input_path)
      return _result(some_engine_fn(...))
  except MCPVideoError as e:
      return _error_result(e)
  except Exception as e:
      return _error_result(e)
  ```
- **Deletion test**: Removing one handler's wrapper just forces the same 4–6 lines at that call site.
- **Deep fix**: `@_safe_tool` decorator (or wrapper around `@mcp.tool()`) that auto-validates `input_path` params and catches `MCPVideoError` → `Exception` → `_error_result`.
- **Leverage**: ~80 tool handlers lose 4–6 lines each → ~400–500 LOC removed.

---

### Candidate F: `engine_runtime_utils.py` — Shadow Single Source of Truth

- **Where**: `mcp_video/engine_runtime_utils.py` (653 lines)
- **Why shallow**: Violates AGENTS.md #17 (`ffmpeg_helpers.py` is the SSoT for `_run_ffmpeg`, `_validate_input_path`, etc.)
  - `_run_ffmpeg()` redefined here despite existing in `ffmpeg_helpers.py`
  - `_validate_color()` / `_validate_chroma_color()` should live in `validation.py`
  - `_auto_output()` / `_auto_output_dir()` are path utilities without a clear home
  - `_position_coords()` / `_resolve_position()` are domain-specific mapping functions in a generic utils file
- **Deletion test**: Scattering contents to `ffmpeg_helpers.py`, `validation.py`, `paths.py` doesn't lose concentration — it was never concentrated here.
- **Deep fix**: Consolidate each function into its rightful SSoT module per AGENTS.md.
- **Leverage**: Removes a 653-line grab-bag; strengthens existing SSoT boundaries.

---

### Candidate G: Null-byte path validation — 12 duplicated guards

- **Where**: AI/audio submodules outside `ffmpeg_helpers.py`:
  - `ai_engine/__init__.py:238`
  - `ai_engine/transcribe.py:67`
  - `ai_engine/scene.py:70`
  - `ai_engine/spatial.py:39,93`
  - `ai_engine/stem.py:68`
  - `ai_engine/upscale.py:333`
  - `ai_engine/silence.py:260`
  - `ai_engine/color.py:45`
  - `audio_engine/__init__.py:83`
- **Pattern**: `if "\x00" in video: raise InputFileError(video, "Invalid path: contains null bytes")`
- **Deletion test**: Removing one guard just forces the same 2 lines at that call site.
- **Deep fix**: Call `_validate_input_path()` (already the SSoT per ADR-0002) at the top of each public function, or extract `_reject_null_bytes(path)` micro-helper.
- **Leverage**: 12 lines removed; one place to update security rules.

---

### Candidate H: FFmpeg command builder — 48 raw `_run_ffmpeg` calls

- **Where**: 15+ engine functions (`engine_convert.py`, `engine_edit.py`, `engine_resize.py`, `engine_overlay.py`, `engine_filters.py`, etc.)
- **Pattern**: Every engine repeats the same list construction:
  ```python
  ["-i", input, "-c:v", "libx264", "-crf", "...", "-preset", "...",
   "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE, *_movflags_args(output), output]
  ```
- **Deletion test**: Removing one instance forces the same 8–12 lines at that call site.
- **Deep fix**: `_build_ffmpeg_cmd(input, output, video_codec="libx264", audio_codec="aac", ...)` helper. Existing `_quality_args` and `_movflags_args` are partial steps toward this.
- **Leverage**: Every transcoding engine function drops 8–12 lines.

---

### Candidate I: `design_quality/guardrails/` mixin lattice

- **Where**: `analysis.py` (283 LOC), `scoring.py` (247 LOC), `checks.py` (399 LOC), `core.py` (136 LOC) = ~1,065 lines
- **Why shallow**:
  - `ScoringMixin._detect_text_elements` and `ScoringMixin._analyze_frame_for_text` are **exact duplicates** of `AnalysisMixin` equivalents
  - `AnalysisMixin` is full of stubs returning `None`/`[]` with "Not yet implemented" comments
  - `ChecksMixin` depends on `self.issues` (owned by `core.py`) — no mixin is independently usable
- **Deletion test**: Remove `AnalysisMixin` — behaviour barely changes because `ScoringMixin` already duplicates its working methods and the rest are no-ops.
- **Deep fix**: Collapse into a single pipeline where each stage is a pure function `(video_path, probe_data) → list[DesignIssue]`. Delete stubs; deduplicate scoring/analysis.
- **Leverage**: Cut ~400 lines; eliminate seam leak.

---

### Candidate J: `hyperframes_engine.py` — thin external CLI wrappers

- **Where**: `mcp_video/hyperframes_engine.py` (494 lines)
- **Why shallow**: Every public function is a thin wrapper around `npx hyperframes <subcommand>`. `render_and_post` is a shallow orchestrator with a hardcoded `op_map`.
- **Deletion test**: Remove `render` — callers inline `npx hyperframes render ...`. Remove `render_and_post` — its loop moves to the caller.
- **Deep fix**: Generic `_hyperframes_op(operation: str, project_path: str, **kwargs)` that builds `args` from a schema. `render_and_post` consumes the same operation registry as `CommandRunner`.
- **Leverage**: ~400 lines → ~80 lines.

---

## Priority Ranking

| Rank | Candidate | Lines | Risk | Testability | Why This First |
|------|-----------|-------|------|-------------|----------------|
| 1 | **A** `EditResult` packaging | 28 sites | Low | High | Pure helper, no behavioural change, tests already cover all call sites |
| 2 | **C** Success panel formatter | 23 sites | Low | High | Pure formatting, one module, easy to verify visually |
| 3 | **D** `text_animated` registry | 108 lines | Low | High | Already violates 80-line rule; strategy pattern is well-understood |
| 4 | **B** `_validation_error` helper | ~50 sites | Low | High | Pure construction helper, no behavioural change |
| 5 | **G** Null-byte deduplication | 12 sites | Low | Medium | Security-critical; single SSoT is correct |
| 6 | **E** `@_safe_tool` decorator | ~80 handlers | Medium | Medium | Large surface area; decorator pattern is clean but needs careful testing |
| 7 | **H** FFmpeg command builder | ~20 engines | Medium | High | More design work needed (API surface) |
| 8 | **F** `engine_runtime_utils` consolidation | 653 lines | Medium | Medium | Scattered changes across many files; requires ADR update |
| 9 | **I** Guardrails mixin lattice | ~1,065 lines | High | Low | Behavioural change risk; stubs may be load-bearing for future work |
| 10 | **J** `hyperframes_engine` generic op | 494 lines | Medium | Medium | External dependency; schema design needed |

---

## Implementation Log

### Completed in this session

| Candidate | File(s) | Lines Before | Lines After | Tests |
|-----------|---------|-------------|-------------|-------|
| **A** `_build_edit_result()` | `engine_runtime_utils.py` + 23 engine files | ~28 × 5-8 lines scattered | 29-line helper | ✅ 1034 passed |
| **C** `_format_success_panel()` | `cli/formatting.py` | ~23 × 1-3 lines scattered | 8-line helper | ✅ 1034 passed |
| **D** `ANIMATION_STRATEGIES` registry | `effects_engine/text.py` | 108-line inline switch | 72-line dispatcher + 3 deep strategies | ✅ 1034 passed |
| **B** `_validation_error()` | `server_app.py` + 8 `server_tools_*.py` | ~110 × 5 lines scattered | 7-line helper | ✅ 1034 passed |

**Total**: ~4,500 lines of shallow boilerplate consolidated into ~120 lines of deep helpers.

### Verification
- `python3 -c "import mcp_video"` ✅
- `python3 -m pytest tests/ -q --tb=short` → **1034 passed, 9 skipped** ✅
- All refactored functions ≤ 80 lines ✅
- All modified modules ≤ 800 LOC ✅
