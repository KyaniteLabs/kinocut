# Sound acceptance fixture freeze (L0.5b)

**Date:** 2026-08-12  
**Status:** frozen for residual program  

| Field | Value |
|-------|--------|
| fixture_id / version | `sound-bench-v1` |
| clip_count band | 50–80 (current evidence: **64**) |
| evidence path | `docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json` |
| required host classes | Apple silicon + x86 Linux (both) |
| cold/warm | both required |
| gate | complete under **30 minutes** wall time per class |
| missing class | residual `external_host_unavailable` — **never pass by skip** |
| capability manifest (from evidence) | `d41_bed`, `d41_audition`, `d42_style`, `d42_identity` |

## Metric schema (required on re-run)

```json
{
  "fixture_version": "sound-bench-v1",
  "hardware_class": "apple_silicon|x86_linux",
  "clip_count": 64,
  "cold_seconds": 0.0,
  "warm_seconds": 0.0,
  "cold_ok": true,
  "warm_ok": true,
  "under_30m": true,
  "required_capabilities": {},
  "digest": "sha256:..."
}
```

**PR language:** no “full-episode complete” until Wave F residual + L3 claim owner.
