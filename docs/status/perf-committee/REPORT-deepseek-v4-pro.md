# Performance committee report — deepseek-v4-pro (inspect only)

Scope: 360 assembly, hot FFmpeg path, import/startup. No code changed. No `public_claims.json` touch. No "optimized" product claim.

## 1. Bottom line

- The 360 render path is **FFmpeg-pass-bound, not Python-bound**: a `split`/`pip` render runs **3 full decode+encode passes** over the same equirect source (one `extract_camera_clip` per camera, then a `split_screen`/`overlay_video` composition pass). Collapsing these into one `filter_complex` invocation is the single highest-value fix.
- The **post-render quality gate is the hidden second cost**: `assert_quality` runs 2–3 full-frame decodes of the output (signalstats + loudnorm + tblend motion) *after* the encode, roughly comparable to the encode itself on short clips.
- Import/startup is already in good shape: PEP 562 (`kinocut/__init__.py:101`) made bare `import kinocut` p50 ≈ 2 ms. Residual startup cost is cold-CLI process time (doctor p50 ≈ 2.6 s), driven by optional-integration subprocess probes, not module import.
- `probe_360_source` hashes the **entire source file** (`sphere_probe.py:102`) and the propose path can do it more than once — negligible on the tiny fixture, but a full read of a multi-GB 360 file on every propose.
- No rewrite, no vendor SDK, no parallel-subprocess fan-out is warranted. The wins are pass-elimination and gate-sampling.

## 2. Measured / code-traced bottlenecks

**Measured on this host** (Darwin/arm64, Python 3.14.5, FFmpeg 8.1; 2 s 640×320 synthetic equirect → 16:9 render):

| step | time |
| --- | --- |
| `probe_360_source` (ffprobe + full-file sha256) | ~50 ms |
| `extract_camera_clip` ×1 (v360 encode, 960×540) | ~120 ms |
| `render_sphere_plan` split (2 extracts + split_screen + quality gate) | ~1353 ms |
| `pytest tests/test_sphere_assembly.py` (11 tests, all layouts) | 7.17 s |

**Code-traced (why each one costs):**

- **`kinocut/te/sphere_render.py:22` `render_sphere_plan`** — the loop at `:41` calls `_render_window` per window. For `split` (`:77`) and `pip` (`:105`), two `extract_camera_clip` calls each spawn a separate FFmpeg encode of the same source range, then `split_screen`/`overlay_video` spawn a **third** encode. Three full decode+encode passes of identical footage = ~3× the necessary work. `switch` (`:132`) is N extracts + one `merge`.
- **`kinocut/te/sphere_storyboard.py:64` `extract_camera_clip`** — one `_run_ffmpeg` per camera; no codec/preset is set so FFmpeg defaults apply; `-ss` is correctly placed *before* `-i` (input seek), so seeking is not the cost — the repeated decode is.
- **`kinocut/te/sphere_render.py:164` `_maybe_quality` → `kinocut/quality_guardrails.py:738` `assert_quality`** — always runs after every render. `run_all_checks` (`:669`) triggers full-pass decodes: `_get_all_signalstats` (`:88`, one full ffprobe decode), `check_audio_levels` (`:399`, full `ffmpeg -af loudnorm` decode when audio exists, plus an extra `_has_audio_stream` ffprobe), and `check_motion` (`:618`, full `ffprobe tblend=difference` decode). On the measured split render this gate added materially to the 1353 ms wall time even though the synthetic clip has no audio.
- **`kinocut/engine_merge.py:119` `merge`** — for `switch`, probes every clip (`probe(c)`, N ffprobe spawns) and `_build_edit_result` probes the output again; the concat itself is already `-c copy` (`:92`), so the overhead is probe-spawn, not encode.
- **`kinocut/te/sphere_probe.py:102` `_file_sha256`** — hashes the whole file in 1 MiB chunks on every `probe_360_source` call; `propose_360_assembly` + `apply_director` can invoke it twice (heuristic fallback + director path). Only matters for large real-world 360 sources.
- **Startup** — `kinocut/__init__.py:101` `__getattr__` correctly keeps heavy engines/`Client` off the import path (bare import p50 0.0023 s; `+Client` p50 0.415 s). Doctor's cold-process p50 ≈ 2.6 s is dominated by `COMMAND_CHECKS` subprocess probes (ffmpeg/ffprobe/node/npx/npm/python versions) and the two Node probes (`npx --yes hyperframes --version`, `@hyperframes/core` `node -e`), not by Kinocut imports.

## 3. Ranked fixes (proposal only — not implemented)

| # | Fix | Effort | Impact | Risk | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | **Single-pass `filter_complex` for split/pip/switch.** Build one FFmpeg invocation that decodes the equirect source once and emits both v360 views plus `hstack`/`overlay`/`xfade` in the same graph. | S–M | High (≈50–66% fewer encode passes on split/pip) | Med | Replaces `sphere_render.py:77/105/132`. Keep output byte-comparable semantics; `tests/test_sphere_assembly.py` (11 cases) already guards behavior. Respect 800-LOC/80-line limits → new helper module or split functions. |
| 2 | **Sample/bound the post-render quality gate.** Run brightness/contrast/saturation + motion on a bounded segment (first N seconds or N frames) instead of the full clip; skip `loudnorm` when `_has_audio_stream` is false without a second ffprobe; make the gate opt-in for `allow_fail` renders. | S | Med (≈halves post-encode time) | Low | Touches `quality_guardrails.py:399/618` and `_maybe_quality`. Must keep `tests/test_visual_intelligence_reframe.py` and quality tests green; sampling changes exact pass/fail thresholds, so gate it behind a flag and default conservative. |
| 3 | **Cache/defer the full-file sha256.** Memoize digest per (path, size, mtime) in-process; skip the duplicate hash on the director fallback path. | S | Low–Med (large sources only) | Low | `sphere_probe.py:102`. Pure, no output change; keeps `sha256:` in the plan unchanged. |
| 4 | **Doctor: defer optional-integration probes.** Run the two Node probes (and other optional checks) behind a flag or a short-lived on-disk cache. | M | Med (cuts cold doctor p50) | Med | `doctor.py` `COMMAND_CHECKS` + `_check_hyperframes_*`. Changes doctor semantics; covered by doctor tests. |

## 4. What I would not do (waste)

- **No stitcher / cubemap decode / face tracking / vendor SDK.** Out of scope per brief; `v360=e:flat` is already correct for equirect→rectilinear.
- **No rewriting FFmpeg in Python** (no hand-rolled decode, no pyav pipeline). Subprocess FFmpeg is the right call.
- **No per-camera parallel FFmpeg fan-out.** It would multiply CPU/memory contention and error-handling surface for less benefit than fix #1's pass elimination.
- **No micro-optimization of Python string building / `_format_ffmpeg_number` / `_run_ffmpeg`'s inner `import`.** Subprocess + decode dominate; these are nanoseconds-to-microseconds noise.
- **No "optimized" claim and no `docs/public_claims.json` bump** — timing/benchmark work is baseline scaffolding (WP-F), not a product fact.
- **No re-encode where `-c copy` already suffices** — `merge`'s concat path already copies; don't "fix" what isn't broken.

## 5. Evidence (commands run, key output)

- `python3 -m pytest tests/test_sphere_assembly.py -q` → `11 passed in 7.17s` (all layouts: split/switch/pip/single + probe/storyboard/director).
- `python3 -m kinocut doctor --json` → `success: true`, `required_ok: true`, 35 checks / 20 passed, `ffmpeg 8.1`, `ffprobe 8.1`, Python 3.14.5, `sphere_director` present, `alias_identity: kinocut.Client is mcp_video.Client`.
- Inline microbenchmark (2 s synthetic equirect, no repo edits): `probe_360_source 50.2 ms`; `extract_camera_clip 120.5 ms`; `render_sphere_plan (split) 1353 ms` (quality gate logged a low-contrast/color-cast/static-motion failure on the synthetic flat clip, confirming the gate ran post-encode).
- Import seam already on disk (`docs/status/golden-path-timings.md`, recorded 2026-08-13): bare `import kinocut` p50 0.0023 s; `import kinocut` + first `Client` p50 0.4151 s; cold `doctor` p50 2.6102 s, `info` p50 1.426 s (new interpreter per sample).
