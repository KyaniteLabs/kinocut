# Performance committee report — Grok

**Seat:** dispatch grok-build (grok-4.5)  
**Mode:** inspect-only · no product code edits  
**Scope:** 360 assembly · FFmpeg hot path · import/startup  
**Branch observed:** `feat/360-generic-equirect` (worktree local inspect)  
**Not a product claim:** nothing here marks Kinocut “optimized.”

---

## 1. Bottom line

- **Dominant 360 cost is multi-encode composition**, not plan validation: default `split`/`pip` do 2× `v360` extract + 1× compose encode; `switch` does N extracts + merge.
- **`extract_camera_clip` is an under-specified FFmpeg hot path**: raw `_run_ffmpeg` args, no `-c:v` / `-preset` / `-crf` via `_build_ffmpeg_cmd` / `_quality_args`.
- **Propose path always full-file SHA-256s the equirect** before any render; multi-GB sources pay pure I/O on every plan.
- **Package import is already fixed (PEP 562 ~2–100 ms cold); cold `kino doctor` is still multi-second** (this host ~6.6 s) from CLI handler fan-in + diagnostics probes.
- **Cheapest wins:** intermediate encode flags + single-pass `filter_complex` for split/pip; defer or sample hash; lazy CLI/doctor imports. Leave stitchers, cubemaps, and Python rewrites alone.

---

## 2. Measured or code-traced bottlenecks

### A. 360 assembly multi-pass encode (high)

| Site | What happens | Why it hurts |
| --- | --- | --- |
| `kinocut/te/sphere_render.py:35` | Windows rendered sequentially via list comprehension | Independent windows never overlap; multi-window plans serialize wall time |
| `sphere_render.py:62–63` | `single` → one `extract_camera_clip` | Baseline: 1 decode+`v360`+encode (OK) |
| `sphere_render.py:89–101` | `split` → left extract + right extract + `split_screen` | **3 full video encodes**; compose re-scales/hstack after already sizing each half |
| `sphere_render.py:116–128` | `pip` → base + pip extracts + `overlay_video` | **3 encodes**; second pass re-reads intermediates |
| `sphere_render.py:143–160` | `switch` → N sequential extracts + `merge` | N+1 hops; merge may normalize/re-encode (`engine_merge.py:159–170`) |
| `sphere_plan.py:172–180` | Default `switch` is **two single windows** | Still 2 extracts (+ optional merge if multi-piece), not one graph |
| `sphere_storyboard.py:25–28` | Storyboard stills: one FFmpeg per camera, sequential | C process spawns; no batch filter |

Code-traced hop model (no long encode run):

| Layout | FFmpeg encodes (code path) |
| --- | --- |
| single | 1× extract |
| split | 2× extract + 1× split_screen = **3** (+2 probes in split_screen) |
| pip | 2× extract + 1× overlay = **3** |
| switch (N cams in one window) | N× extract + 1× merge |
| storyboard (C cams) | C× still |

### B. FFmpeg hot path quality / cmd construction (high)

| Site | Issue |
| --- | --- |
| `sphere_storyboard.py:79–91` (`extract_camera_clip`) | Builds `[-y, -ss, -i, -t, -vf v360, out]` only. **No** `_build_ffmpeg_cmd`, **no** `-c:v libx264`, **no** `DEFAULT_PRESET`/`DEFAULT_CRF` |
| `sphere_filters.py:10–16` | `v360=e:flat:...` is fine and number-escaped; filter string itself is not the bottleneck |
| `ffmpeg_helpers.py:279–311` (`_run_ffmpeg`) | Correct timeout/error path; always spawns a new process; capture_output only (no progress) |
| `ffmpeg_helpers.py:443–511` (`_build_ffmpeg_cmd`) | Standard encode path used by overlay/merge engines — **not used by sphere extract** |
| `limits.py:72–73` | Defaults: `DEFAULT_CRF=23`, `DEFAULT_PRESET="fast"` — apply elsewhere, not to intermediate sphere temps |
| `engine_split_screen.py:46–47, 84–98` | Re-probes both inputs then re-encodes hstack; sphere already chose exact pixel sizes |
| `engine_overlay.py:87–96` | Third encode for pip; uses quality args only if caller passes crf/preset (sphere does not) |
| `sphere_render.py:40, 164–173` | `assert_quality` after every render adds probe/signal work on top of assembly |

**v360 cost itself** (equirect → rectilinear) is real FFmpeg CPU; the avoidable waste is **doing it into temp MP4s then re-encoding** instead of one `filter_complex` with two `v360` branches + `hstack`/`overlay`.

### C. Propose / probe I/O (medium–high for large sources)

| Site | Issue |
| --- | --- |
| `sphere_probe.py:30–53` | Every propose: reject raw → validate path → ffprobe → **full SHA-256** |
| `sphere_probe.py:102–107` | Streams entire file in 1 MiB chunks (`DEFAULT_HASH_CHUNK_BYTES`) |
| `sphere_plan.py:198` | Schema requires `source.sha256` — cannot drop digest without schema/policy change |

Geometry check is cheap (one ffprobe). Full-file hash scales with source size and dominates propose for multi-GB Insta360/GoPro equirect exports.

### D. Import / startup (medium for CLI; low for package)

| Measurement (this host, cheap probes) | Result |
| --- | --- |
| In-process `import kinocut` (warm session) | **2.6 ms** |
| Cold process `import kinocut` | **~104 ms** |
| Cold `from kinocut.te import sphere_assembly` | **~1.03 s** |
| Cold `from kinocut.doctor import run_diagnostics` | **~376 ms** |
| Cold `import kinocut.__main__` | **~261 ms** (eager handler imports only) |
| Cold `python -m kinocut doctor --json` wall | **6.642 s**, rc=0 |
| `tests/test_sphere_assembly.py` | **11 passed in 11.01 s** |
| Disk baseline (`docs/status/golden-path-timings.md`) | doctor cheap p50 **2.6–5.3 s**; bare import after PEP 562 p50 **0.0023 s**; first Client **~0.4 s** |

Root causes (code-traced):

| Site | Issue |
| --- | --- |
| `kinocut/__init__.py:14–112` | PEP 562 lazy map — **already good**; bare import not the CLI problem |
| `kinocut/__main__.py:9–29` | Eager imports of **all** CLI handler modules on every process start |
| `kinocut/doctor.py:17–18` | Module-level import of `hyperframes_engine` (cold ~129 ms alone) even for core-only doctor |
| `doctor.py` COMMAND_CHECKS / PACKAGE_CHECKS | Many subprocess version probes + optional package specs; sequential wall time |

---

## 3. Ranked fixes (effort × impact × risk)

Do **not** implement here — proposals only. Keep custom errors, filter escaping, 800/80 LOC rules.

| Rank | Fix | Effort | Impact | Risk | Notes |
| ---: | --- | :---: | :---: | :---: | --- |
| 1 | **Single-pass split/pip**: one FFmpeg with `filter_complex` = `v360…[a]; v360…[b]; [a][b]hstack` (or overlay) from the equirect | M | **High** | Med | Collapse 3 encodes → 1; keep receipt/tests; escape numbers via existing helpers |
| 2 | **Route `extract_camera_clip` through `_build_ffmpeg_cmd`** with explicit libx264 + intermediate preset (`veryfast`/`ultrafast`) + higher temp CRF; final delivery keep `DEFAULT_PRESET`/`DEFAULT_CRF` | S | **High** (intermediates & single) | Low | Defaults live in `defaults.py`/`limits.py`; no magic numbers |
| 3 | **Defer full SHA-256** to approve/render receipt; propose may use size+mtime+partial sample, with schema flag if needed | S–M | High on multi-GB propose | Med | Tests assert sha256 today (`test_sphere_assembly`); keep fail-closed final digest |
| 4 | **Lazy CLI entry**: import only the handler path for the selected subcommand; stop loading all handlers in `__main__` | M | High for doctor/info cold start | Low–Med | Aligns with existing server lazy-import doctrine |
| 5 | **Doctor slim path**: defer `hyperframes_engine` import; optional `--core` or skip optional package checks unless `--full` | S | Med–High on doctor p50 | Low | Golden-path cheap step benefits immediately |
| 6 | **Parallel independent window extracts / storyboard stills** (bounded worker pool + `DEFAULT_*` concurrency limit) | S–M | Med | Med | Watch disk thrash on single HDD; prefer after single-pass graph |
| 7 | **Skip redundant probe in sphere→split_screen/overlay** when plan already fixed dimensions | S | Low–Med | Low | Pass known geometry or sphere-local compose helper |
| 8 | **Quality gate**: keep default; document `allow_fail`/async QC for bulk; avoid dropping gate silently | S | Low (UX) | Low | Correctness > micro-savings |

---

## 4. What you would **not** do (waste)

- **Do not** rewrite FFmpeg graphs in pure Python / numpy frame loops.
- **Do not** add stitchers, cubemap decode, face tracking, or vendor SDKs (brief forbid + wrong bottleneck).
- **Do not** chase bare `import kinocut` further — PEP 562 already meets ≤0.40 s aim; first Client ~0.4 s is mixin cost, separate from 360.
- **Do not** default all encodes to `ultrafast` delivery quality without an intermediate-vs-final distinction.
- **Do not** GPU/hwaccel as first move without a measured v360 bottleneck on target hosts.
- **Do not** bump `docs/public_claims.json` or claim “optimized” from this inspect.
- **Do not** micro-optimize `_format_ffmpeg_number` / validation regexes — not on the wall-clock critical path.
- **Do not** parallelize across machines for single-file assembly; local graph reduction wins first.

---

## 5. Evidence: commands and key output

### Commands run (cheap only)

```text
codegraph explore "360 sphere assembly render ffmpeg hot path"
codegraph explore "extract_camera_clip sphere_storyboard v360 ffmpeg filter"
# static reads of sphere_*.py, ffmpeg_helpers.py, doctor.py, __main__.py, engine_{split,overlay,merge}.py
python3 -c "import time; ... import kinocut; from kinocut.te import sphere_assembly; ..."
python3 -m pytest tests/test_sphere_assembly.py -q --tb=line
kino doctor --json   # truncated head
python3 -c "subprocess.run([sys.executable,'-m','kinocut','doctor','--json'], ...)"  # wall timing
# cold subprocess import matrix for kinocut, sphere_assembly, doctor, __main__, ffmpeg_helpers
```

### Key output (abridged)

```text
import kinocut (in-process): 2.6ms
import sphere_assembly (in-process after kinocut): 261.3ms
import render+storyboard+ffmpeg_helpers (already loaded): 0.0ms

Cold process imports (approx):
  import kinocut:                              104ms
  from kinocut.te import sphere_assembly:     1029ms
  from kinocut.te.sphere_probe import ...:     603ms
  from kinocut.te.sphere_render import ...:    646ms
  from kinocut.ffmpeg_helpers import ...:      205ms
  from kinocut.doctor import run_diagnostics:  376ms
  import kinocut.__main__:                     261ms
  import kinocut.hyperframes_engine:           129ms

pytest tests/test_sphere_assembly.py: 11 passed in 11.01s

doctor --json: success=true, required_ok=true, ffmpeg 8.1, total_checks=34, passed=11
doctor cold wall: 6.642s rc=0

Encode defaults: CRF=23 PRESET=fast TIMEOUT=600
Sphere extract: no -c:v / preset / crf flags (rg confirmed)
```

### On-disk timing receipt (not re-run full golden path)

From `docs/status/golden-path-timings.md` (2026-08-13 cheap + import seam):

| step | p50 (s) | note |
| --- | ---: | --- |
| doctor cheap | 2.61 | cold CLI process; varies 1.4–5.3 across days |
| info cheap | 1.43 | cold CLI |
| `import kinocut` after PEP 562 | 0.0023 | engines not loaded |
| `import kinocut` + first Client | 0.415 | mixin cost |

### Encode hop model (code-traced)

```text
single:  1x extract_camera_clip
split:   2x extract + 1x split_screen = 3 encodes (+2 probes)
pip:     2x extract + 1x overlay_video = 3 encodes
switch:  N extract + 1 merge (possible normalize re-encode)
storyboard: C sequential still extracts
propose: 1 ffprobe + full-file sha256
```

---

## Committee note

Highest leverage is **fewer FFmpeg generations on the 360 hot path** (single filter graph + explicit intermediate encode settings), then **I/O on propose (hash policy)** and **CLI/doctor cold start**. Package-level lazy import is already in good shape; do not spend cycles there first.
