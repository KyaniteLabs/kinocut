# Sound program S13–S15 historical gate receipt

**Date:** 2026-07-14  
**Scope:** Historical dual-class synthetic benchmark evidence only. This receipt is not final 1.8.0 release authorization.

## S13 — Host joins (COMPLETE)

In-repo D41/D42 owners are bound under `kinocut.sound_joins`.

Owners used (not invented):

1. **D41** — `kinocut.engine_audio_bed.audio_bed` via `KinocutBedAdapter` / `KinocutAuditionAdapter`
2. **D42** — `kinocut.aivideo.voice_seam` / audio fingerprint path via `KinocutStyleAdapter` / `KinocutIdentityAdapter`

Sidecar boundary preserved: `kinocut_sound` still imports no `kinocut.*`. Host joins live under `kinocut/sound_joins/`.

Evidence:

- Focused tests: `tests/test_kinocut_sound_joins_s13.py` green in the recorded execution
- Real adapter ids: `d41_bed_kinocut_audio_bed`, `d41_audition_kinocut`, `d42_style_kinocut_voice_seam`, `d42_identity_kinocut_voice_seam`
- Probe requires local ffmpeg (+ sidechaincompress/loudnorm for D41 bed)

Remaining optional host surfaces (not blocking this join): full WF text-card narrator wire-through, review-package/learning controller registration, CLI/MCP tool registration of the bound ports.

## S14 — Historical benchmark evidence

The versioned synthetic 64-clip fixture completed on both required classes. Public evidence uses only the benchmark receipt allowlist.

| Class | Cold (s) | Warm (s) | Cold/Warm | Under 30m |
| --- | ---: | ---: | --- | --- |
| x86_linux | 0.3957 | 0.3862 | pass/pass | yes |
| apple_silicon | 0.0743 | 0.0737 | pass/pass | yes |

- Fixture: `sound-bench-v1`, 64 clips (within 50–80 band)
- Scheduler: `BoundedProcessPool` with max workers, max tasks, wall-clock ceiling, cancel/resume
- Evidence file: `docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json`
- Digests: see evidence file (x86 `32ef9609…`, apple `a9b3d9e2…`)

## S15 — Historical acceptance stop

Commands executed after S12 merge:

- S1–S14 implementable path closed with this change unit (S13/S14 code + dual-class evidence)
- Focused S13/S14 suites green
- Dual-class cold/warm under 30 minutes
- Public receipts use the fixed benchmark allowlist

Still required before any ship at the time of this historical receipt:

- Independent architecture review package on the full sound program
- Explicit human release authorization
- Optional full-season real-media acceptance beyond the synthetic fixture

The final 1.8.0 release packet supersedes this receipt for current release gating.
