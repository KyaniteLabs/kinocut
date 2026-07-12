# Plan 02 — Wave 3 (Verdict/Protection/Salvage) + Wave 4 (Audio Continuity) + Wave 5 (Subtitle & Graphics QA)

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change. No release actions (index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §4.4–4.6, §5.1, §5.3–5.5, §6 Wave 3–5; coverage #1, #5–7, #17–18, #23–35, #41.

> **For implementers:** Work task-by-task in bounded branches with independent review.

**Goal:** Turn inspection evidence into governed editorial decisions and safe media output: explicit clip verdicts with a protected-element mutation gate, body-swap and salvage derivatives that prove audio/source preservation, one-shot audio beds with auditions and honest voice-seam metrics, and deterministic subtitle/graphics QA.

**Architecture:** Compose over Plan 00 contracts and Plan 01 inspection artifacts. Verdicts and defects are `ClipVerdict`/`DefectFinding` records; the mutation gate computes a touched dependency set and fails with `protected_element_change` on collision (design §4.6 — no force flag for agents). Body swap is a NEW engine primitive with explicit pad/trim/reject policy that verifies audio preservation via the existing rescue-verifier fingerprint helpers (`kinocut/rescue/verifier.py` `_packets`:60, `_monotonic`:81, `_stream_counts`:96, `_av_end_delta`:104; `verify_package`:138). Salvage extends rescue operations (clean prefix/suffix, freeze extension, still, region crop, background-only) with lineage. Audio bed is one governed facade over `audio_compose` (`kinocut/server_tools_audio.py:193`, engine `kinocut/audio_engine/sequencing.py:353`), `duck_audio` (`kinocut/engine_audio_ops.py:191`), and `normalize_audio` (`kinocut/engine_audio_normalize.py:25`). Voice-seam metrics clamp ASR to EOF (Plan 01 `kinocut/subtitles_eof.py`) before pace/cadence/silence/loudness, using `ai_transcribe` (`kinocut/ai_engine/transcribe.py:43`). Graphics recipe is deterministic composition over the shipped compositor `composite_layers` (`kinocut/engine_composite_layers.py:119`), `watermark` (`kinocut/engine_watermark.py:24`), `overlay_video` (`kinocut/engine_overlay.py:33`), `add_text`/`add_texts` (`kinocut/engine_text.py:40/159`), and `effects_engine/text.py` builders.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, FFmpeg via `kinocut/ffmpeg_helpers.py`, optional local Whisper + optional pitch/speaker-embedding providers (fail-soft), pytest 8+ real-media fixtures, Ruff.

## Global Constraints (subset — see index §3)

- The only editorial dispositions are the seven `ClipVerdict` values; `approved_with_trim` needs a bounded range; `rejected`/`regenerate` cannot enter approved-only search (design §4.4).
- Every mutating op computes its touched dependency set before rendering; a protected-element collision fails `protected_element_change` unless a NEW explicit human review authorizes it — no force flag (design §4.6).
- Salvage never overwrites an original; every derivative has lineage, operation policy, output hash, and a fresh verdict (design §5.3).
- Body swap defaults to preserving approved audio and rejecting a video-duration mismatch; `pad_video`/`trim_video`/`trim_audio` must be explicit; audio-preserving ops compare packet/stream fingerprints and fail the preservation gate if the declared guarantee is not met (design §5.1).
- ASR segments are clamped to real EOF before any pace/cadence/silence/seam metric; the clamp is recorded as a warning/finding (design §5.1).
- Audio bed owns the one-shot policy (exact duration, loop seams/crossfades, ducking, fades, loudness target, true-peak ceiling, receipt); bed audition uses the same ship-level mix policy and never auto-updates bed approval (design §5.4).
- Important exact text/logos are deterministic editor layers, never trusted to generated pixels (design §5.5).
- FFmpeg escaping, custom errors, timeouts, additive compatibility, MCP/Python/CLI parity, optional-capability fail-soft; no release actions (index §3, §3.6).

## File Structure

### Wave 3 — new production files

- `kinocut/aivideo/verdict.py` — public verdict + defect-taxonomy APIs over Plan 00 contracts; acceptance-spec evaluation report.
- `kinocut/aivideo/protection.py` — protected-element mutation precheck: `touched_dependencies(op) -> set`, `assert_no_protected_collision(project, op)`.
- `kinocut/engine_body_swap.py` — NEW primitive: replace video track, explicit duration policy, approved-audio preservation, packet/stream fingerprint verifier.
- `kinocut/aivideo/salvage.py` — clean prefix/suffix, freeze extension, still, region crop, background-only derivatives with lineage (extends `kinocut/rescue/` operations + `engine_crop.py`, `engine_frames.py`, `engine_freeze`/`engine_speed.py`).
- MCP/CLI/Python surfaces: `video_verdict`, `video_acceptance_eval`, `video_body_swap`, `video_salvage`.

### Wave 4 — new production files

- `kinocut/audio_engine/bed.py` — one-shot audio bed facade (exact duration, loop crossfades, ducking, fades, loudness/true-peak, receipt).
- `kinocut/audio_engine/audition.py` — labeled equal-duration bed audition reel under the real voice, same ship-level mix policy.
- `kinocut/aivideo/voice_seam.py` — EOF-clamped deterministic loudness/pace/silence metrics + optional pitch/cadence + optional speaker embeddings; aggregate `AudioSeamReport`.
- Surfaces: `video_audio_bed`, `video_bed_audition`, `video_voice_seam_report`.

### Wave 5 — new production files

- `kinocut/aivideo/subtitle_qa.py` — cue overlap/gap/reading-speed/EOF checks + platform-safe-area profiles + full-resolution samples (reuses Plan 01 `clamp_segments_to_eof`).
- `kinocut/aivideo/graphics_recipe.py` — deterministic receipt-bound text/logo/caption composition over `composite_layers`.
- Surfaces: `video_subtitle_qa`, `video_graphics_recipe`.

### New tests

- Wave 3: `tests/test_aivideo_verdict.py`, `tests/test_aivideo_protection.py`, `tests/test_body_swap.py`, `tests/test_aivideo_salvage.py`, `tests/test_wave3_surfaces.py`.
- Wave 4: `tests/test_audio_bed.py`, `tests/test_bed_audition.py`, `tests/test_voice_seam.py`, `tests/test_wave4_surfaces.py`.
- Wave 5: `tests/test_subtitle_qa.py`, `tests/test_graphics_recipe.py`, `tests/test_wave5_surfaces.py`.

### Documentation

- `docs/AI_VIDEO_VERDICTS.md`, `docs/KINOCUT-AUDIO-FEATURES.md` update, `docs/AI_VIDEO_SUBTITLE_QA.md`; additive CLI/TOOLS/PYTHON refs. No release entries.

---

## PR 3.1 — Editorial verdict and defect workflow (#1, #5–7)

### Task 1: Verdict + acceptance evaluation + protected-element precheck

**Files:** Create `kinocut/aivideo/verdict.py`, `kinocut/aivideo/protection.py`; Test `tests/test_aivideo_verdict.py`, `tests/test_aivideo_protection.py`.

**Interfaces:** Consumes Plan 00 `ClipVerdict`, `DefectFinding`, `ProtectedElement`, `GenerationAcceptanceSpec`, project store.

- [ ] **Step 1: Failing tests**

```python
def test_rejected_verdict_excluded_from_approved_search(project):
    record_verdict(project, _verdict(disposition="rejected"))
    assert approved_clips(project) == []

def test_protected_collision_fails_without_new_human_decision(project):
    lock = protect(project, _element())          # ProtectedElement
    op = _mutation_touching(lock)
    with pytest.raises(MCPVideoError) as e:
        assert_no_protected_collision(project, op)
    assert e.value.code == "protected_element_change"

def test_acceptance_eval_lists_unmet_beats_and_forbidden_defects(project):
    report = acceptance_eval(project, spec=_spec(required_beats=["intro"]), verdicts=[])
    assert "intro" in report.unmet_required
```

- [ ] **Step 2: RED** — `python3 -m pytest -q tests/test_aivideo_verdict.py` → import error.
- [ ] **Step 3: Implement** verdict recording (binds exact asset hash + optional trim range), acceptance evaluation (required subjects/actions/beats/text/logos vs verdicts + forbidden defect thresholds), and the mutation precheck computing the touched dependency set and comparing against every `ProtectedElement` fingerprint. No force path.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_aivideo_verdict.py tests/test_aivideo_protection.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): editorial verdict, acceptance eval, protected-element gate"`.

---

## PR 3.2 — Body swap and audio preservation proof (#17, #28)

### Task 2: Body-swap primitive with preservation verifier

**Files:** Create `kinocut/engine_body_swap.py`; Test `tests/test_body_swap.py`.

**Interfaces:** Consumes `_run_ffmpeg`, rescue-verifier helpers (`_packets` verifier.py:60, `_stream_counts`:96, `_av_end_delta`:104), Plan 00 `PreservationProof`.

- [ ] **Step 1: Failing tests**

```python
def test_body_swap_preserves_approved_audio_by_default(tmp_path, clip_a, clip_b):
    res = body_swap(video_source=str(clip_b), audio_source=str(clip_a), output_path=str(tmp_path/"o.mp4"))
    proof = res["preservation_proofs"][0]
    assert proof["verdict"] == "preserved"          # audio packets identical

def test_duration_mismatch_rejected_unless_explicit(tmp_path, clip_10s, clip_7s):
    with pytest.raises(MCPVideoError) as e:
        body_swap(video_source=str(clip_7s), audio_source=str(clip_10s), output_path=str(tmp_path/"o.mp4"))
    assert e.value.code in {"validation_error","protected_element_change"}
```

- [ ] **Step 2: RED** → **Step 3: Implement** the primitive: default preserves approved audio and rejects video-duration mismatch; `pad_video`/`trim_video`/`trim_audio` are explicit opt-ins; compute source/output audio packet+stream fingerprints and emit a `PreservationProof`; fail the preservation gate if the declared guarantee is not met.
- [ ] **Step 4: Green (fixtures)** — stream-copy preservation, multi-stream, mismatch rejection.
- [ ] **Step 5: Commit** — `git commit -m "feat(engine): body swap with audio preservation proof"`.

---

## PR 3.3 — Salvage derivatives (#18)

### Task 3: Lineage-bound salvage operations

**Files:** Create `kinocut/aivideo/salvage.py`; Test `tests/test_aivideo_salvage.py`.

**Interfaces:** Consumes `engine_crop.py`, `engine_frames.py`, `engine_speed.py`/freeze, rescue operations; Plan 00 lineage.

- [ ] **Step 1: Failing tests** — clean prefix/suffix trim, freeze-extension, still-frame, region-crop, and background-only derivatives each (a) never overwrite the original, (b) record lineage + operation policy + output hash, and (c) produce a fresh `ClipVerdict` slot (not auto-approved).
- [ ] **Step 2: RED** → **Step 3: Implement** the five derivative recipes with content-addressed outputs and lineage links.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_aivideo_salvage.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): lineage-bound salvage derivatives"`.

### Task 4: Wave 3 surfaces + gate

**Files:** MCP/CLI/Python for `video_verdict`, `video_acceptance_eval`, `video_body_swap`, `video_salvage`; Test `tests/test_wave3_surfaces.py`.

- [ ] Steps: failing parity tests → RED → implement with `@mcp.tool()`/`@_safe_tool`/`_result` + `CommandRunner.register` → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo kinocut/engine_body_swap.py` → leak audit → `git commit -m "feat(aivideo): wave 3 verdict/salvage surfaces"`.

> **Parallel note:** PR 3.2 and PR 3.3 own disjoint engines and may run concurrently after PR 3.1 lands (design §7).

---

## PR 4.1 — One-shot audio bed and audition (#23–24, #41 seam)

### Task 5: Governed audio-bed facade

**Files:** Create `kinocut/audio_engine/bed.py`; Test `tests/test_audio_bed.py`.

**Interfaces:** Consumes `audio_compose` (audio_engine/sequencing.py:353), `duck_audio` (engine_audio_ops.py:191), `normalize_audio` (engine_audio_normalize.py:25).

- [ ] **Step 1: Failing tests** — bed hits an exact target duration via loop seams/crossfades; applies voice-driven ducking, fades, loudness target and true-peak ceiling; emits a receipt with the mix policy; a longer/shorter bed than target is handled by policy, not silently truncated.
- [ ] **Step 2: RED** → **Step 3: Implement** the single facade owning the one-shot policy; reuse existing compose/duck/normalize primitives; escape user values.
- [ ] **Step 4: Green (fixtures)** — bed shorter/longer than target, loudness seam, ducking under voice.
- [ ] **Step 5: Commit** — `git commit -m "feat(audio): one-shot governed audio bed"`.

### Task 6: Bed audition reel

**Files:** Create `kinocut/audio_engine/audition.py`; Test `tests/test_bed_audition.py`.

- [ ] **Step 1: Failing tests** — audition produces labeled equal-duration candidate sections under the real voice using the SAME ship-level mix policy as final composition; it never updates bed approval automatically.
- [ ] **Step 2: RED** → **Step 3: Implement** the audition recipe.
- [ ] **Step 4: Green + commit** — `python3 -m pytest -q tests/test_bed_audition.py && git commit -m "feat(audio): bed audition reel"`.

> **Parallel note:** PR 4.1 and PR 5.1 may run concurrently after their shared contracts land (design §7).

---

## PR 4.2 — Voice seam metrics and report (#25–27, #30)

### Task 7: EOF-clamped deterministic metrics + optional providers + report

**Files:** Create `kinocut/aivideo/voice_seam.py`; Test `tests/test_voice_seam.py`.

**Interfaces:** Consumes Plan 01 `clamp_segments_to_eof` (`kinocut/subtitles_eof.py`), `ai_transcribe` (ai_engine/transcribe.py:43), `_analyze_loudnorm` (quality_guardrails.py:240); optional pitch/speaker-embedding providers.

- [ ] **Step 1: Failing tests** — ASR segments are clamped to real EOF before any metric and the clamp is recorded as a warning/finding; deterministic loudness/pace/silence metrics compute without ML; optional pitch/cadence and speaker-embedding providers are capability-gated and fail-soft; the aggregate `AudioSeamReport` composes #25–29 without a separate analyzer stack.
- [ ] **Step 2: RED** → **Step 3: Implement** the clamp-first pipeline and aggregate report; unavailable providers yield typed `capability_unavailable` entries.
- [ ] **Step 4: Green (fixtures)** — ASR past EOF, loudness/speaker seams, silent source.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): EOF-clamped voice seam metrics and report"`.

---

## PR 5.1 — Subtitle temporal and safe-area QA (#33–34)

### Task 8: Cue QA + platform safe-area profiles

**Files:** Create `kinocut/aivideo/subtitle_qa.py`; Test `tests/test_subtitle_qa.py`.

**Interfaces:** Consumes `clamp_segments_to_eof`, subtitle parsing from `kinocut/engine_subtitles.py`/rescue verifier, `_run_ffprobe_json`.

- [ ] **Step 1: Failing tests** — reports cue overlap, gaps, reading-speed (chars/sec) violations, missing lines, and EOF overflow as `DefectFinding`s; platform-safe-area profiles flag subtitle/overlay collisions at full display resolution.
- [ ] **Step 2: RED** → **Step 3: Implement** deterministic QA + safe-area profiles + full-resolution sample crops.
- [ ] **Step 4: Green (fixtures)** — overlaps, gaps, reading-speed and EOF failures, safe-area collisions across vertical/horizontal/square.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): subtitle temporal and safe-area QA"`.

---

## PR 5.2 — Deterministic graphics recipe (#35)

### Task 9: Receipt-bound graphics composition

**Files:** Create `kinocut/aivideo/graphics_recipe.py`; Test `tests/test_graphics_recipe.py`.

**Interfaces:** Consumes `composite_layers` (engine_composite_layers.py:119, `_build_filter_complex`:487, `_build_layer_plan`:560), `watermark`, `overlay_video`, `add_text`/`add_texts`, `effects_engine/text.py` builders.

- [ ] **Step 1: Failing tests** — a prescribed text/logo/caption recipe is deterministic for the same inputs and binds source assets/fonts + receipt hashes; important exact text/logos are editor layers (assert the recipe never routes exact text through a generative path).
- [ ] **Step 2: RED** → **Step 3: Implement** the recipe over the shipped compositor; escape all user values.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_graphics_recipe.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): deterministic receipt-bound graphics recipe"`.

### Task 10: Wave 4–5 surfaces + full-suite gate

**Files:** MCP/CLI/Python for `video_audio_bed`, `video_bed_audition`, `video_voice_seam_report`, `video_subtitle_qa`, `video_graphics_recipe`; Test `tests/test_wave4_surfaces.py`, `tests/test_wave5_surfaces.py`.

- [ ] Steps: failing parity tests → RED → implement surfaces → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo kinocut/audio_engine` → leak audit → `git commit -m "feat(aivideo): wave 4-5 audio and subtitle/graphics surfaces"`.

---

## Wave 3–5 completion criteria

- Verdicts are the closed seven dispositions; the protected-element gate fails closed with no force flag; acceptance evaluation lists unmet beats and forbidden defects.
- Body swap and audio-preserving ops emit verified `PreservationProof`s; salvage derivatives never overwrite originals and carry lineage + fresh verdicts.
- Audio bed hits exact duration with honest seam handling; auditions never auto-approve; voice-seam metrics clamp ASR to EOF first and fail-soft on optional providers.
- Subtitle QA and graphics recipe are deterministic; exact text/logos are editor layers.
- All design §8 fixture families for audio preservation, subtitles, and salvage are exercised with real FFmpeg; MCP/Python/CLI parity + backward fixtures green; full suite green; canonical import passes; Ruff clean; modules ≤ 800 LOC.
- Independent review approved; no self-approval; no release actions (index §3.6).
- Downstream: Plan 03 (asset intelligence + planning) consumes approved verdicts/beds; Plan 04 (review) consumes seam/subtitle reports and preservation proofs.
