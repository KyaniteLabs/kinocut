# Perf committee report — Kimi K3 seat

**Mode:** inspect-only. No edits to `kinocut/`, `tests/`, README, or `public_claims.json`.
**Host:** Darwin/arm64, Python 3.14.5. Not an "optimized" product claim — baseline receipts only.

## 1. Bottom line

- The 360 split/pip render pipeline decodes the source once per camera **and re-encodes 3 times** (2 v360 extracts + 1 hstack/overlay compose) where **one** `filter_complex` pass (one decode, one encode) would do. This is the top bottleneck.
- Every 360 render ends with `assert_quality`, which runs **3 additional full-length decode passes** over the output (signalstats ffprobe, loudnorm ffmpeg, tblend temporal-motion ffmpeg). On long 360 footage the gate can cost as much as the render itself.
- `probe_360_source` reads the **entire source file** to compute sha256 on every propose (`kinocut/te/sphere_probe.py:102`). Fine for test clips; seconds of extra disk I/O for multi-GB 360 footage.
- `kino doctor --json` is 6.4–9.9 s wall (measured). ~60% is sequential subprocess checks and ~40% is import cost, of which the largest single item is `_check_alias_identity` importing `mcp_video`, whose `from kinocut import *` (`mcp_video.py:12`) **eagerly loads every PEP 562-lazy engine** (55+ modules) — silently defeating the lazy-import work documented in `docs/status/golden-path-timings.md`.
- PEP 562 startup is otherwise healthy: bare `import kinocut` p50 0.06 s; first `Client` access 0.80 s. Leave it alone.

## 2. Measured or code-traced bottlenecks

### 360 assembly hot path

- `kinocut/te/sphere_render.py:88-101` (`_render_split`): two sequential `extract_camera_clip` calls (each a full source-segment decode + libx264 encode), then `split_screen` which runs 2 `probe()` ffprobes and a third encode. Measured on a 4 s 640×320 synthetic equirect: 3 ffmpeg encodes = 0.23 + 0.26 + 0.42 s of a 1.74 s render; the same structure at 4K/minutes-long scales linearly with decode cost. Same pattern in `_render_pip` (`sphere_render.py:105-129`) and `_render_switch` (`sphere_render.py:132-161`, N extracts + merge).
- `kinocut/te/sphere_render.py:40` → `kinocut/quality_guardrails.py:688-701`: quality gate = 1 ffprobe signalstats pass (`_get_all_signalstats`, `:88`) + 1 ffmpeg loudnorm pass (`_analyze_loudnorm`, `:271`) + 1 ffmpeg tblend pass (`_measure_temporal_motion`, `:541`) + `_has_audio_stream` ffprobe (`:315`). Signalstats is already batched/cached (good); loudnorm and temporal-motion are not.
- `kinocut/te/sphere_probe.py:102-107` (`_file_sha256`): full-file read per propose. Provenance-grade, but O(file size) on every plan.
- `kinocut/te/sphere_storyboard.py:33-53`: one ffmpeg process per camera still — acceptable (N small single-frame jobs), minor.

### FFmpeg helpers (shared)

- `kinocut/ffmpeg_helpers.py` itself is in good shape: centralized runners, timeouts, byte-caps on stderr, caching probe. No duplication found. The cost is *how many times* callers invoke it, not the helpers.
- `kinocut/engine_split_screen.py:46-47`: re-probes both intermediates immediately after we just wrote them with known geometry — redundant ffprobe work.

### Import/startup & doctor

- `mcp_video.py:12` `from kinocut import *`: star-import forces `kinocut.__getattr__` for all 41 lazy names → eager import of client, ai_engine, audio_engine, effects_engine, transitions_engine, design_quality, quality_guardrails, contracts (verified: 55+ `kinocut.*` modules in `sys.modules` after `import mcp_video`). Measured `import mcp_video`: p50 1.89 s cold vs `import kinocut` 0.06 s.
- `kinocut/doctor.py:398` (`_check_alias_identity`) triggers the above inside every `doctor` run: cProfile of in-process `run_diagnostics` = 6.6 s wall, of which ~2.7 s is import machinery and ~3.9 s is 9 sequential `_command_version` subprocesses.
- `kinocut/doctor.py:193`: `npx --yes hyperframes --version` is the slowest single check (0.66 s warm, worse cold) and runs whenever node exists, even when the caller only wants core status.
- `kinocut/doctor.py:18`: top-level `from .hyperframes_engine import ...` costs ~0.3–0.4 s at `import kinocut.doctor` before any check runs.
- `python3 -m kinocut doctor --json` measured 6.38 / 9.87 / 8.26 s wall (3 runs), user time only ~3.7 s → roughly half the wall is waiting on subprocesses.

### Test suite (signal, not a product defect)

- `pytest tests/test_sphere_assembly.py`: 11 passed in ~15–17 s. Slowest: `test_switch_window_with_two_cameras_renders` 3.37 s, `test_intent_goal_and_doctor_honesty` 2.62 s (runs full diagnostics), layout renders ~2 s each. Confirms the per-render multi-process cost above.

## 3. Ranked fixes (effort × impact × risk)

| # | Fix | Effort | Impact | Risk |
|---|-----|--------|--------|------|
| 1 | Collapse split/pip/switch renders into a single `filter_complex` (`v360` per camera → `hstack`/`overlay`/`trim+concat` in one ffmpeg process; 1 decode, 1 encode, no intermediate files, no re-probes). Localize in `sphere_render.py`; keep `_run_ffmpeg`, custom errors, escaped numbers via `v360_filter`. | M | **High** (eliminates ~2/3 of encode+decode work per 360 render) | Medium — changes intermediate-artifact layout under `_sphere_work`; receipts must keep the same shape; golden tests must stay green |
| 2 | Stop `mcp_video.py`'s eager star-import: forward attributes lazily (module-level `__getattr__` delegating to `kinocut`) so `import mcp_video` ≈ `import kinocut`. Directly cuts ~1.5–1.9 s cold from every doctor run and every legacy import. | S | **High** for doctor/startup | Low — alias semantics already covered by the doctor identity check and `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"` |
| 3 | Quality gate: fold loudnorm + signalstats + temporal-motion into fewer passes (one ffmpeg with combined filtergraph/metadata, or sampled frames for the advisory temporal check) and/or cache per output path. | M | Medium–High (scales with output duration; gate currently ≈ render cost on long clips) | Medium — must preserve scores/verdicts byte-for-byte or re-baseline |
| 4 | Doctor: run the 9 `_command_version` probes concurrently (threads) and skip `npx --yes hyperframes --version` unless a hyperframes command was actually resolved; lazy-import `hyperframes_engine` inside `run_diagnostics`. | S | Medium (doctor wall ~6.6 s → ~2–3 s) | Low — diagnostics only, no render path |
| 5 | `split_screen`: accept optional pre-known geometry to skip the 2 `probe()` calls when inputs were just rendered by us. | S | Low–Medium | Low |
| 6 | `_file_sha256`: bound provenance hashing (e.g. head+tail+size) or make it lazy/cached per path+mtime. | S | Low (only matters on multi-GB sources) | Medium — weakens provenance integrity; needs owner sign-off |
| 7 | Parallelize the per-camera extracts when >1 camera (threads around `_run_ffmpeg`). Only worth it if fix #1 is rejected. | S | Medium | Low |

## 4. What I would **not** do (waste)

- Do not rewrite FFmpeg orchestration in Python or add stitchers/cubemap decode/vendor SDKs — out of scope and explicitly forbidden by the brief.
- Do not touch `ffmpeg_helpers.py` internals (`_run_ffmpeg`, `_run_command`, `_atomic_output`) — they are already centralized, timed-out, and capped; churn there is pure risk.
- Do not micro-optimize `v360_filter`/`_format_ffmpeg_number` — string formatting is nanoseconds next to any decode.
- Do not add caching layers to `merge`/`split_screen` probe calls before fix #1; fix #1 removes those probes entirely.
- Do not parallelize doctor's package `find_spec` checks — they are already microseconds; the subprocesses are the cost.
- Do not "optimize" bare `import kinocut` further (0.06 s) or the first-Client mixin cost (0.8 s) without a measured user complaint — the PEP 562 seam already met its ≤0.4 s bare-import aim.
- Do not bump `docs/public_claims.json` or use "optimized" wording from any of this.

## 5. Evidence: commands and key output

- `python3 -m pytest tests/test_sphere_assembly.py -x -q --tb=short` → **11 passed in 15.03s**; `--durations=6` → render tests 1.9–3.4 s each, doctor-honesty test 2.62 s.
- `/usr/bin/time -p python3 -m kinocut doctor --json` ×3 → wall **6.38 / 9.87 / 8.26 s**, user ~3.6–3.8 s (≈50% subprocess wait).
- cProfile of in-process `run_diagnostics()` → **6.63 s**: 9 `_command_version` subprocess calls = 3.93 s cumulative (largest: `npx --yes hyperframes --version` 0.66 s warm, `hyperframes --version` 0.23 s, `npx`/`npm --version` ~0.10 s each); import machinery = 2.67 s.
- Import probes (new interpreter, p50 of 3): `import kinocut` 0.062 s · `import kinocut.doctor` 0.328 s · `import kinocut.hyperframes_engine` 0.397 s · `import kinocut; kinocut.Client` 0.801 s · `import kinocut.cli.runner` 0.128 s · `import mcp_video` **1.889 s cold / 0.36 s warm** with 55+ heavy `kinocut.*` modules eagerly loaded (verified via `sys.modules`).
- End-to-end 360 render probe (synthetic 640×320 equirect, 4 s, instrumented `_run_ffmpeg`): propose 0.05 s; approve+render 1.74 s with exactly 3 ffmpeg encodes (0.23/0.26/0.42 s) + ~0.8 s of probes, merge/rename and quality gate. Same shape scales to real footage.
- `probe_360_source` on the tiny golden fixture: 0.12 s (sha256 cost is trivial at 10 KB, linear in file size).
- `quality_check` on the golden fixture: 0.13 s (fixture is 4 frames; cost is per-frame and scales with output length).
