# Performance committee report — GLM seat

**Scope:** inspect-only. 360 assembly (`kinocut/te/sphere_*.py`), FFmpeg hot path
(`kinocut/ffmpeg_helpers.py`, `engine_merge.py`, `quality_guardrails.py`),
import/startup (`kinocut/__init__.py`, `kinocut/client/meta.py`), and the
on-disk evidence in `docs/status/golden-path-timings.md`. No source edited.

---

## 1. Bottom line

- **The 360 render is subprocess-fanout bound, not filter bound.** A single
  2-camera window on a 6 s source spawns 6 `ffmpeg` + 14 `ffprobe` processes
  (split) and 6 `ffmpeg` + 14 `ffprobe` (switch); `single` is 2 + 8. Most of
  those spawns re-decode a file that was just written.
- **The quality gate is the largest fixed cost per render.**
  `assert_quality` runs ~5–7 independent `ffprobe` passes that each fully
  decode the rendered output (sharpness, signalstats, color, motion via
  `tblend+difference`). It bypasses the `probe()` cache entirely.
- **Per-window composition decodes the source 2–3×.** `_render_split`/`_render_pip`
  do two `extract_camera_clip` calls (each opens + decodes the source range and
  re-encodes an intermediate) then a compose pass that decodes those
  intermedials again. One `filter_complex` pass would decode once, encode once.
- **Startup is already cheap where it matters.** Bare `import kinocut` is ~3 ms
  (PEP 562). The real cold cost is first `Client` access (~0.47–0.65 s), driven
  by `kinocut/client/meta.py:7` eagerly pulling `server_tools_basic` → `mcp.types`
  (the `mcp` SDK alone is ~1.4 s cumulative under `-X importtime`).
- **Safe wins exist that do not change product behaviour:** collapse the quality
  gate's redundant decodes into one `signalstats` pass, and let `merge` skip
  re-probing clips the caller just produced. Both are S-effort, Low-risk.

---

## 2. Measured / code-traced bottlenecks

### 2.1 360 render — process fanout (measured)

Bench: 6 s `testsrc` equirect 1280×640, one window, `allow_fail=True` (quality
gate runs but cannot fail the render), 3 samples, process counts via
`subprocess.run`/`Popen` instrumentation.

| layout | wall p50 (s) | ffmpeg procs | ffprobe procs |
| --- | ---: | ---: | ---: |
| single (1 cam) | 2.58 | 2 | 8 |
| split (2 cam)  | 5.32 | 6 | 14 |
| pip (2 cam)    | 7.77 | 8 | 12 |
| switch (2 cam) | 9.72 | 6 | 14 |

Tracing where they come from:

- `kinocut/te/sphere_render.py:77` `_render_split` → 2 × `extract_camera_clip`
  + `split_screen(...)` (`:101`). Each `extract_camera_clip`
  (`kinocut/te/sphere_storyboard.py:67`) is its own `ffmpeg` decoding the source
  range through `v360` and re-encoding an intermediate; `split_screen` then
  decodes both intermediates. **Source decoded 3×, two generation-lossy
  intermediate encodes.**
- `kinocut/te/sphere_render.py:105` `_render_pip` → 2 × extract + `overlay_video`
  (`:128`). Same pattern.
- `kinocut/te/sphere_render.py:132` `_render_switch` → N × extract + `merge(clips)`
  (`:160`). Cheap compose (concat `-c copy`, see 2.3) but still N independent
  source decodes.

### 2.2 Quality gate re-decodes the output repeatedly (code-traced + measured)

`kinocut/quality_guardrails.py` spawns its own `ffprobe` via raw `subprocess.run`
at **lines 114, 155, 231, 284, 567**, plus `_run_ffprobe_json` at `:318`. Each of
those `ffprobe` invocations runs a `lavfi` graph (`signalstats`, `tblend=...`,
`entropy`, color stats) that **fully decodes the rendered output**. None of them
go through the cached `engine_probe.probe()` path (`engine_probe.py:119`,
cached by path/mtime/size at `:20`). On a short render this fixed cost dominates
the actual encode — visible in the bench as the gap between `single` (2.58 s, 1
real encode) and the multi-camera layouts.

### 2.3 `merge` probes clips it just wrote (code-traced)

`kinocut/engine_merge.py:142` runs `infos = [probe(c) for c in clips]`
**unconditionally**, before the `needs_normalize` decision (~`:150`). For 360
output every clip comes from the same plan (identical width/height/codec/fps),
so `needs_normalize` is almost always `False` and those N probes are computed
and discarded. The fast path that follows is good — `_concat_clips` (`:92`) uses
the concat demuxer with `-c copy` — but the throwaway probes still cost one
`ffprobe` spawn per clip on first render of a fresh file.

### 2.4 First-`Client` import cost (measured)

`/usr/bin/time -p python3 -c "import kinocut; kinocut.Client"` → real 0.47–0.65 s.
`-X importtime` attributes the bulk to:

- `mcp.types` self 459 748 µs / cumulative 1 443 442 µs, reached via
  `kinocut/client/meta.py:7` → `kinocut/server_tools_basic.py:7`
  (`from mcp.types import ToolAnnotations`).
- `kinocut/contracts/_common` self 70 560 µs (pydantic schema build).
- `kinocut/models` 129 933 µs, plus the pydantic/pydantic_settings stack.

Bare `import kinocut` (no attribute access) is ~3.6 ms — the PEP 562 gate in
`kinocut/__init__.py:101` is doing its job and should be left alone.

### 2.5 Minor: two overlapping ffprobe helpers (code-traced)

`ffmpeg_helpers._get_video_duration` (`:560`) and `_run_ffprobe_json` (`:584`)
are separate ffprobe entry points doing overlapping work; `engine_probe.probe`
wraps the JSON one with a cache. Not a hot bottleneck, but a dedup target.

---

## 3. Ranked fixes (effort × impact × risk)

| # | Fix | Effort | Impact | Risk | Where |
| --- | --- | --- | --- | --- | --- |
| 1 | Collapse the quality gate's ~5–7 `ffprobe` decode passes into **one** `filter_complex`/`signalstats` pass over a single decode of the output (emit YAVG + color + sharpness + entropy in one graph). Route through the `probe()` cache. | **S** | **M–H** (removes 3–5 full output decodes per render; biggest win on short clips) | **Low–Med** — must keep per-metric scores bit-identical vs current; validate against existing fixtures | `quality_guardrails.py:114/155/231/284/318/567` |
| 2 | Let `merge()` take pre-supplied `infos` (or `homogeneous=True`) so `_render_switch`/callers skip the unconditional `probe()` at `engine_merge.py:142` for clips they just produced. | **S** | **M** (cuts N throwaway `ffprobe` per multi-clip render) | **Low** — cache already makes repeats safe | `engine_merge.py:142`, `sphere_render.py:160` |
| 3 | Single-pass `filter_complex` for split/pip windows: one `-i source`, two `v360=...` branches into `hstack`/`overlay`, one encode. Replaces 2–3 extract+compose passes. | **M** | **H** (decode source once, encode once; removes intermediate generation loss) | **Med** — new render byte output; keep multi-pass path as fallback; receipts + quality gate must stay green | `sphere_render.py:77/105`, new helper |
| 4 | Lazy-import `server_tools_basic`/`mcp.types` out of `kinocut/client/meta.py:7` so `Client` construction does not eagerly pull the ~1.4 s `mcp` SDK until a tool search actually runs. | **S** | **S–M** (shaves first-`Client` cold cost; no effect on bare import) | **Low–Med** — mixin must still resolve on first tool call | `kinocut/client/meta.py:7` |
| 5 | Dedupe `_get_video_duration` vs `_run_ffprobe_json` to one ffprobe call site. | **S** | **S** | **Low** | `ffmpeg_helpers.py:560/584` |

All proposals keep the custom-error / escape / 800-LOC / 80-line limits. No fix
here touches `docs/public_claims.json` or asserts "optimized" as a product fact.

---

## 4. What I would NOT do (waste)

- **Rewrite FFmpeg in Python / add a stitcher / cubemap decoder / vendor SDK.**
  The `v360` filter is CPU-bound inside FFmpeg and already optimal; evidence
  shows the bottleneck is process fanout and redundant decodes, not the
  projection math.
- **Touch `kinocut/__init__.py` PEP 562 gate.** Bare import is ~3 ms, already
  under the 0.40 s aim noted in `golden-path-timings.md`. Pre-warming `Client`
  at import would *regress* this.
- **Daemonise FFmpeg or link it as a shared library.** Huge risk, marginal win
  next to fixes #1–#3.
- **Run long encodes as a "benchmark".** Out of scope; cheap probes + the
  on-disk golden timings are sufficient evidence.
- **Bump `public_claims.json` or label anything "optimized".** Forbidden until
  an L3 claim-owner PR with durable p50/p95.

---

## 5. Evidence (commands run + key output)

```
# Python / tooling on this host
$ python3 --version            -> Python 3.14.5
$ ffmpeg -version | head -1    -> ffmpeg version 8.1
$ command -v pytest            -> /opt/homebrew/bin/pytest  (binds Python 3.11)
```

**Import seam (`-X importtime`, dominant contributors):**

```
import time:    459748 |     459748 |           mcp.types
import time:       469 |    1443425 |       mcp                 # via client/meta -> server_tools_basic
import time:     57390 |    1504400 |     kinocut.server_tools_basic
import time:       224 |    1504624 | kinocut.client.meta
import time:     70560 |     70720 |         kinocut.contracts._common
import time:    129933 |     396318 |         kinocut.models
import time:       519 |      5193 | kinocut                    # bare import (PEP 562)
```

```
$ for i in 1 2 3 4 5; do /usr/bin/time -p python3 -c "import kinocut" 2>&1 | grep real; done
real 0.03 / 0.03 / 0.03 / 0.03 / 0.04

$ for i in 1 2 3 4 5; do /usr/bin/time -p python3 -c "import kinocut; kinocut.Client" 2>&1 | grep real; done
real 0.48 / 0.47 / 0.52 / 0.50 / 0.65
```

**Doctor (cold CLI):**

```
$ for i in 1 2 3; do /usr/bin/time -p python3 -m kinocut doctor --json >/dev/null 2>/tmp/t; grep real /tmp/t; done
real 2.11 / 2.87 / 1.98          # 35 checks; matches golden-path-timings p50 ~2.6 s
```

**Sphere assembly tests (must use the project Python, not PATH pytest):**

```
$ python3 -m pytest tests/test_sphere_assembly.py -q
...........                                                              [100%]
11 passed in 10.83s
```

> Note (environment, not a code issue): bare `pytest tests/test_sphere_assembly.py`
> fails on this workstation because `/opt/homebrew/bin/pytest` binds Homebrew
> Python 3.11, whose stale `mcp` SDK lacks `ToolAnnotations`
> (`ImportError: cannot import name 'ToolAnnotations' from 'mcp.types'`).
> `python3 -m pytest` (3.14, correct `mcp`) passes cleanly. Worth flagging for
> the runbook; no source change implied.

**360 render subprocess counts (6 s 1280×640 equirect, 1 window, allow_fail):**

```
single   wall=2.58s  ffmpeg=2  ffprobe=8
split    wall=5.32s  ffmpeg=6  ffprobe=14
pip      wall=7.77s  ffmpeg=8  ffprobe=12
switch   wall=9.72s  ffmpeg=6  ffprobe=14
```

**Cross-check vs on-disk evidence** (`docs/status/golden-path-timings.md`):
doctor p50 2.6 s, info p50 1.4 s, bare `import kinocut` p50 0.0023 s,
first `Client` access ~0.4 s — consistent with the measurements above.

**File/line references cited:** `kinocut/te/sphere_render.py:77,105,132`,
`kinocut/te/sphere_storyboard.py:67`, `kinocut/engine_merge.py:92,142`,
`kinocut/quality_guardrails.py:114,155,231,284,318,567`,
`kinocut/engine_probe.py:20,119`, `kinocut/ffmpeg_helpers.py:560,584`,
`kinocut/client/meta.py:7`, `kinocut/server_tools_basic.py:7`.
