# Sol performance committee report

## 1. Bottom line

- The dominant 360 cost is repeated full video encoding: each virtual camera extract encodes once, then split/PiP encodes the composite again. A two-camera window therefore performs three encodes before final assembly.
- The safest high-impact fix is a single FFmpeg filtergraph per window: decode the equirectangular source once, split it into camera branches, apply `v360`, then compose and encode once.
- Storyboard generation starts one FFmpeg process and decodes/seeks the same source once per camera; a single multi-output graph is the next best 360 optimization.
- Bare PEP 562 import is already cheap (local p50 0.0259 s). Cold `Client` access (local p50 0.8051 s) and CLI startup are the remaining import/startup seams; do not spend effort micro-optimizing `kinocut/__init__.py`.
- The scoped test passed (11 tests), and `doctor --json` completed successfully in 3.03 s. These are local inspection results, not a product optimization claim.

## 2. Measured or code-traced bottlenecks

1. **Repeated decode + encode for composed 360 windows.** `kinocut/te/sphere_render.py:35` renders every window serially. For split, `kinocut/te/sphere_render.py:89-101` calls `extract_camera_clip` twice and then `split_screen`; PiP repeats the pattern at `kinocut/te/sphere_render.py:116-128`. Each camera extraction invokes FFmpeg with `v360` and writes an encoded MP4 (`kinocut/te/sphere_storyboard.py:77-92`), while split/PiP invokes another FFmpeg composition (`kinocut/engine_split_screen.py:81-98`, `kinocut/engine_overlay.py:79-97`). This is the largest traced multiplier: two source decodes and three encodes for one two-camera window.
2. **Switch layout also repeats source startup and encoding.** `kinocut/te/sphere_render.py:143-160` launches one camera extraction per segment, followed by merge. The merge can stream-copy compatible outputs (`kinocut/engine_merge.py:92-99`), so the expensive part is the N separate v360 extraction processes, not concatenation itself.
3. **Storyboard repeats seek/decode and process startup per camera.** `kinocut/te/sphere_storyboard.py:25-28` loops serially, and `kinocut/te/sphere_storyboard.py:33-53` starts FFmpeg for one PNG each time. A multi-camera plan repeatedly opens and seeks the same input at the same timestamp.
4. **Extra probe subprocesses surround composition.** After camera intermediates exist, split probes both (`kinocut/engine_split_screen.py:41-48`) and PiP probes the background (`kinocut/engine_overlay.py:59-70`). Final multi-window merge probes every piece (`kinocut/engine_merge.py:141-159`). These are smaller than encoding but scale with windows and are redundant when dimensions, duration, FPS, and codec were just produced under Kinocut's control.
5. **CLI startup eagerly imports the command surface.** Although package import is lazy (`kinocut/__init__.py:101-112`), `python -m kinocut` imports all handler modules before parsing or dispatch (`kinocut/__main__.py:9-28`) and builds the full parser before handling doctor (`kinocut/__main__.py:102-104`). Local cold-process probes: `import kinocut` p50 0.0259 s; `from kinocut import Client` p50 0.8051 s (5 runs, high variance, 0.5209-2.0682 s); `doctor --json` wall time 3.03 s. Existing receipts also show bare import after PEP 562 at 0.0023 s and first `Client` access around 0.4151 s (`docs/status/golden-path-timings.md:132-140`), so the current package seam is effective while full CLI/Client startup remains material and host-variable.
6. **FFmpeg helper capture is not the primary hot-path problem.** `_run_ffmpeg` captures stdout/stderr in memory (`kinocut/ffmpeg_helpers.py:279-311`), but process launch, v360 transform, and encoding dominate normal renders. Changing capture behavior before eliminating encode multiplication would add risk for little likely gain.

## 3. Ranked fixes: effort × impact × risk

| Rank | Proposed fix | Effort | Impact | Risk | Why / acceptance probe |
| ---: | --- | :---: | :---: | :---: | --- |
| 1 | Add a sphere-specific, single-pass per-window renderer: one input, `split` branches, one `v360` per camera, in-graph split/PiP composition, one encode. Keep it in a focused engine/helper under 800 LOC and functions under 80 lines; use existing validation, defaults, escaping/number formatting, timeouts, and custom errors. | M | Very high | Medium | Removes intermediate camera files and reduces a two-camera window from three encodes to one. Golden acceptance: exact duration/layout/audio behavior plus existing sphere tests and a tiny fixture timing comparison. |
| 2 | Render storyboard cameras in one FFmpeg invocation using `split` plus per-branch `v360`, mapping one PNG per camera. | M | High for proposal/review latency | Low-Medium | One input open/seek/decode and one process instead of N. Preserve distinct output validation and failure checks. Compare generated camera count/dimensions and scoped test behavior. |
| 3 | Add an internal trusted-metadata path for sphere-owned intermediates so split/PiP/final merge do not re-probe files whose exact stream contract is already known. Do not weaken public engine guardrails. | M | Medium | Medium | Saves 2+ ffprobe launches per composed window while retaining validation at public boundaries. Receipt metadata must be checked rather than assumed across arbitrary callers. |
| 4 | Lazy-load CLI handler groups and fast-path `doctor`/`--version` after minimal argument recognition; defer unrelated handlers/parser branches until selected. | M | Medium | Medium | Targets cold CLI cost without undoing PEP 562. Require parser-equivalence tests for global options, namespaces, error output, and default MCP behavior. |
| 5 | Cache resolved FFmpeg/FFprobe binary paths in-process if the runtime resolver does not already do so; invalidate only through an explicit test/reset seam. | S | Low | Low | `_run_ffmpeg` resolves the binary on every call (`kinocut/ffmpeg_helpers.py:285-292`). Measure resolver cost first; skip if already cached or negligible. |

Do not parallelize multiple full-resolution v360 encodes as the first fix. It may reduce wall time on a many-core host, but it increases CPU/memory pressure and preserves the wasted work. Fuse work first; consider bounded concurrency only after measurement on representative hardware.

## 4. What I would not do (waste)

- Do not add stitchers, cubemap decode, face tracking, vendor SDKs, or rewrite FFmpeg transforms in Python; none addresses the traced encode multiplier.
- Do not replace the working PEP 562 package API. Bare import is already below the recorded target; optimize selected CLI/Client imports instead.
- Do not globally remove probes or safety checks from public engines. Only bypass redundant probes through a narrow internal contract carrying verified metadata.
- Do not tune CRF/preset or add hardware encoding before establishing a representative 360 fixture baseline. Those choices trade quality, portability, or determinism and can obscure the structural win.
- Do not parallelize every storyboard/window process without a resource cap, and do not retain camera intermediates merely to make parallelism easier.
- Do not claim the product is "optimized" from these traces or cheap probes.

## 5. Evidence

- `codegraph explore "360 sphere assembly render storyboard filters FFmpeg startup doctor bottlenecks"` — located the sphere render/storyboard call graph and public callers before targeted inspection.
- `python3 -m pytest tests/test_sphere_assembly.py -q --tb=short` — **11 passed in 15.53 s**.
- `/usr/bin/time -p python3 -m kinocut doctor --json` — exit 0, valid JSON (`checks`, `migrations`, `platform`, `rescue`, `success`, `summary`), **3.03 s real**.
- Five cold subprocess runs each: `import kinocut` p50 **0.0259 s** (0.0252-0.0266); `from kinocut import Client` p50 **0.8051 s** (0.5209-2.0682). High Client variance means this is directional, not a stable benchmark.
- Inspected the committed timing receipt: doctor p50 ranges from 1.3643 s to 5.26 s across recorded local runs; the latest five-run block is 2.6102 s. That variance reinforces measuring structural changes with paired runs on the same host.
- No encode was run. No product code, tests, README, or claims file was edited. Actual committee inspection elapsed time: approximately 5 minutes (manual timing because lifecycle start estimate was unavailable).
