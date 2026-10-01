# Independent review, 2026-10-01

No model weights, external inference, provider execution or new runtime dependencies. The additional source edit was the long-form ingress repair delegated after an independent reliability review; the other source domains were reviewed read-only.

## Verified defects sent to root

1. `engine_audio_ops.add_audio(start_time=1,fade_in=.5)` schedules the fade at timeline zero after inserting delayed silence. On an actual synthetic 440Hz source, first audible 1.04–1.10s RMS is exactly 1.0 times the no-fade baseline. `fade_out=.5` with 1s audio on a 3s video schedules the fade at 2.5s after the attached sound ends; observed .82–.90s tail RMS also equals the no-fade baseline. Fixtures and machine-readable ratios: `fade-review/proof.json` in this folder. No subjective listening/retention claim.
2. `DesignQualityGuardrails.analyze()` with valid configured FFmpeg/FFprobe executables and PATH empty raises a raw FileNotFoundError for bare `ffprobe`. `design_quality/guardrails/probe.py` and motion/scene paths in `analysis.py` still bypass the shared configured binary resolver. Valid native executable paths were present; proof `design-configured-probe-proof.json`. New canonical color measurement and D41/version fixes did not introduce this old behavior, but do not cover these older seams.

## Long-form ingress repair, now frozen

Independent reviewer reproduced raw OverflowError from timestamps/confidence `10**1000` and TypeError from scalar `segments=7`. `_longform_merge.py` and `_longform_runtime.py` now validate segment/word collection shapes before formatting or iteration, returning custom `invalid_transcript_output` errors. Huge/bool timestamp claims fail with structured `invalid_transcript_timing`; malformed optional confidence becomes unknown None rather than manufactured numeric confidence or a crash. The pre-existing handling of missing/unparseable spans and nonmapping entries is retained. 119 focused long-form tests passed in 0.66s; pinned Ruff check/format passes. No model inference.

## Independent architecture validation

101 tests passed in 33.55s for D41 configured host backend, public client mask composition, workflow version/rescue discovery identity, inspection provider contracts, design color measurements, and design fix safety. No extraction regression found in these repaired paths. Source inspection confirmed the public mask family remains inherited by ClientMediaMixin with original signatures, and quality CLI extraction preserves its existing renderable behavior. The previous bounded independent postflight test proved existing-delivery preservation and staging cleanup for all 15 core writers; that proof occurred before the additional descriptor registry changes, whose implementation is still owned by reliability.

Earlier nearby root findings (preview invalid factors, FPS nonfinite metadata, coded-vs-display resize proportions) have been repaired by root with added controls. Root reported a successful real `-display_rotation:v:0 90` fixture and 300x400 single-axis resize. Earlier self-overwrite writable-registration exemption is being repaired by reliability; no clean claim is made for that work in progress.

## Scope and limitations

No new Windows host proof, learned accuracy benchmark, deployed-ASR replacement identity or full corpus inference. Static registry factories and injected callbacks are trusted Python extension points, not sandboxed code. Reliability separately sent root real 360 stale-source receipt and callback-mutation fallback defects; no duplicate source edits were made here.
