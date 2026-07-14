# Sound program S13–S15 gate receipt

**Date:** 2026-07-14  
**Hosts:** Niko (x86 Linux), Liam Mac mini (Apple silicon)  
**Release:** NOT AUTHORIZED / NOT PERFORMED

## S13 — Host joins (COMPLETE)

**Status:** `complete` — in-repo D41/D42 owners bound under `kinocut.sound_joins`.

Owners used (not invented):

1. **D41** — `kinocut.engine_audio_bed.audio_bed` via `KinocutBedAdapter` / `KinocutAuditionAdapter`
2. **D42** — `kinocut.aivideo.voice_seam` / audio fingerprint path via `KinocutStyleAdapter` / `KinocutIdentityAdapter`

Sidecar boundary preserved: `kinocut_sound` still imports no `kinocut.*`. Host joins live under `kinocut/sound_joins/`.

Evidence:

- Focused tests: `tests/test_kinocut_sound_joins_s13.py` green on Niko
- Real adapter ids: `d41_bed_kinocut_audio_bed`, `d41_audition_kinocut`, `d42_style_kinocut_voice_seam`, `d42_identity_kinocut_voice_seam`
- Probe requires local ffmpeg (+ sidechaincompress/loudnorm for D41 bed)

Remaining optional host surfaces (not blocking this join): full WF text-card narrator wire-through, review-package/learning controller registration, CLI/MCP tool registration of the bound ports.

## S14 — Benchmark (DUAL-CLASS GREEN)

**Status:** complete for the versioned synthetic 64-clip fixture on both required classes.

| Class | Host | Cold (s) | Warm (s) | Under 30m | Status |
| --- | --- | ---: | ---: | --- | --- |
| x86_linux | Niko NUCBox | 0.3957 | 0.3862 | yes | ok |
| apple_silicon | Liam Mac mini | 0.0743 | 0.0737 | yes | ok |

- Fixture: `sound-bench-v1`, 64 clips (within 50–80 band)
- Scheduler: `BoundedProcessPool` with max workers, max tasks, wall-clock ceiling, cancel/resume
- Evidence file: `docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json`
- Digests: see evidence file (x86 `02fe5aed…`, apple `d600f954…`)

## S15 — Acceptance STOP

**Status:** STOP before release.

Performed:

- S1–S14 implementable path closed with this change unit (S13/S14 code + dual-class evidence)
- Focused S13/S14 suites green
- Dual-class cold/warm under 30 minutes
- Privacy: receipts omit host paths and secrets

Still required before any ship (human gates, not engineering green claims):

- Independent architecture review package on the full sound program
- Explicit human release authorization
- Optional full-season real-media acceptance beyond the synthetic fixture

**No version bump, tag, package upload, directory submission, deploy, or announce.**
