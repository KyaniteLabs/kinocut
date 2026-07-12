# Plan 01 — Wave 1 (Field Safety) + Wave 2 (Ingest & Deterministic Inspection)

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change. No release actions (index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §5.1–5.2, §6 Wave 1–2; coverage #2–4, #8, #9–16, #27, #28, #29, #31–32, #36, #38.

> **For implementers:** Work task-by-task in bounded branches with independent review.

**Goal:** Fix the two field-proven safety defects (add-audio eats the outro; subtitles bypass ASS/dimension-awareness) and land content-addressed ingest plus the deterministic temporal-inspection evidence stack. Wave 1 PRs are parallel-safe after Plan 00's PR 0.2 merges because they own disjoint engines; Wave 2 builds the ingest + inspection artifacts that verdicts (Plan 02) depend on.

**Architecture:** Extend shipped engines rather than adding parallel systems. Add-audio safety extends `kinocut/engine_audio_ops.py:add_audio` (add_audio at engine_audio_ops.py:123) with an explicit duration policy — the current tool `video_add_audio` (`kinocut/server_tools_basic.py:295`) exposes NO policy and can inherit shortest-stream behavior (the defect). Subtitles extend `kinocut/engine_subtitles.py:subtitles` (subtitles at engine_subtitles.py:21, SRT/VTT-only today) to accept ASS and to synthesize dimension-aware render settings using probed display dimensions. Ingest and inspection compose over `kinocut/projectstore/` (Plan 00), `kinocut/engine_probe.py`, `kinocut/quality_guardrails.py` (`VisualQualityGuardrails` at quality_guardrails.py:76), `kinocut/engine_storyboard.py`, and `kinocut/engine_frames.py`. All findings are `DefectFinding` records (Plan 00 taxonomy) with `status="suspected"` until a human decision.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, FFmpeg/ffprobe via `kinocut/ffmpeg_helpers.py` (`_run_ffmpeg` :223, `_run_ffprobe_json` :489, `_escape_ffmpeg_filter_value` :451, `_get_video_duration` :465), pytest 8+ with real-media fixtures, Ruff. Optional ML providers (Wave 2.4) fail soft.

## Global Constraints (subset — see index §3)

- `video_add_audio` **defaults to preserving video duration**; audio is padded/looped/trimmed only per explicit policy; `shortest` requires the explicit policy and always emits a duration-change warning (design §5.1).
- ASS input preserves authored styles, positions, PlayRes; SRT/VTT convert through dimension-aware ASS using actual display dimensions (design §5.5).
- Motion strips sample the full playable duration including late/final frames; default temporal percentages 0, 25, 50, 75, 95, and last decodable frame (design §5.2).
- Every FFmpeg user value escaped via `_escape_ffmpeg_filter_value`; all subprocess calls carry `DEFAULT_FFMPEG_TIMEOUT`; errors only from `kinocut/errors.py` (`AGENTS.md`).
- New tool params/fields additive; existing `video_add_audio`/`video_subtitles` signatures keep working with old defaults (index §3.3).
- Optional analyzers return typed `capability_unavailable`; deterministic package stays complete without them (design §3.3, §9).
- MCP + Python client + CLI parity for every public change; backward fixtures for legacy shapes.
- No release actions (index §3.6).

## File Structure

### Wave 1 — modified production files

- `kinocut/engine_audio_ops.py` — add `duration_policy: Literal["keep_video","loop_audio","pad_audio","trim_audio","shortest"]` to `add_audio`; default `keep_video`; emit duration-change warning on `shortest`.
- `kinocut/server_tools_basic.py` — `video_add_audio` gains additive `duration_policy` param (default preserves current-safe behavior) and receipt fields; no positional-arg break.
- `kinocut/client/audio.py` — mirror `duration_policy` on the client method.
- `kinocut/cli/parser/*` + `kinocut/cli/handlers_audio.py` — `--duration-policy` flag.
- `kinocut/engine_subtitles.py` — accept `.ass` input (preserve styles/position/PlayRes); for SRT/VTT synthesize dimension-aware ASS from probed width/height; use a shared EOF-clamp utility.
- `kinocut/engine_subtitle_generate.py` + a new `kinocut/subtitles_eof.py` — shared `clamp_segments_to_eof(segments, eof_seconds)` utility used by generate, burn QA, and ASR (design §5.1 EOF clamp; consumed later by Plan 02 PR 4.2).
- `kinocut/server_tools_media.py` — `video_subtitles` documents ASS support; dimension-aware default.

### Wave 1 — new tests

- `tests/test_add_audio_duration_policy.py` — audio shorter/longer/equal, silent source, multi-stream, `keep_video` default preserves the outro (real-FFmpeg regression for the eaten-outro defect), `shortest` warns.
- `tests/test_subtitles_ass_and_dimension.py` — authored-ASS preservation, vertical/horizontal/square SRT/VTT dimension-aware render, EOF clamp shared utility.

### Wave 2 — new production files

- `kinocut/aivideo/ingest.py` — project ingest facade over `kinocut/projectstore/ingest.py`: stable `asset_id`, generation-metadata + rights fields, technical/loudness/integrity preflight.
- `kinocut/aivideo/preflight.py` — one `PreflightReport` composed over `kinocut/engine_probe.py`, `VisualQualityGuardrails.check_audio_levels`/`_analyze_loudnorm` (quality_guardrails.py:535/240), and integrity probe; adds color/audio/integrity fields.
- `kinocut/aivideo/inspection/motion_strip.py` — deterministic tiled motion strip over `engine_storyboard.py`/`engine_frames.py` with the 0/25/50/75/95/last sampling policy and a receipt artifact.
- `kinocut/aivideo/inspection/samplers.py` — late-frame sampler + declared text/logo region crops (normalized coords, source-resolution extraction, sampled timestamp).
- `kinocut/aivideo/inspection/manifest.py` — `InspectionPackage` manifest (design §4.8) referencing technical metadata, preview, muted preview, motion strip, sampled frames, region crops, frame-diff measurements, findings, and unavailable capabilities.
- `kinocut/aivideo/inspection/temporal_checks.py` — deterministic loop-integrity + black/frozen/duplicate/corrupt interval findings, extending `VisualQualityGuardrails.check_motion`/`_measure_temporal_motion` (quality_guardrails.py:754/677) and `check_brightness` (:373) with bounded-segment reporting.
- `kinocut/aivideo/inspection/providers.py` — capability-gated optional motion-intent + generative-defect analyzers over the same artifacts; absent provider ⇒ typed unavailable capability.
- New MCP/CLI/Python surfaces: `video_ingest`, `video_preflight`, `video_inspect_temporal` (+ client methods + CLI `kino inspect ...` — flat aliases via later Wave 9, but the flat commands land here).

### Wave 2 — new tests

- `tests/test_aivideo_ingest.py`, `tests/test_aivideo_preflight.py`, `tests/test_inspection_motion_strip.py`, `tests/test_inspection_samplers.py`, `tests/test_inspection_manifest.py`, `tests/test_inspection_temporal_checks.py`, `tests/test_inspection_providers.py`, `tests/test_inspection_surfaces.py`.

### Documentation

- `docs/AI_VIDEO_INSPECTION.md`, updates to `docs/CLI_REFERENCE.md`, `docs/TOOLS.md`, `docs/PYTHON_CLIENT.md` (additive only; no CHANGELOG release entry).

---

## PR 1.1 — Loss-proof add-audio (#29, part of #8/#28)

### Task 1: Duration-policy contract + failing eaten-outro regression

**Files:** Modify `kinocut/engine_audio_ops.py`; Test `tests/test_add_audio_duration_policy.py`.

**Interfaces:** Consumes `add_audio(video_path, *, audio_path, volume, fade_in, fade_out, mix, start_time, output_path)` (engine_audio_ops.py:123), `_get_video_duration`, `_run_ffmpeg`. Produces `add_audio(..., duration_policy="keep_video")` + a `duration_warning` in the result.

- [ ] **Step 1: Write the failing real-FFmpeg regression**

```python
def test_keep_video_default_preserves_outro(tmp_path, video_10s, audio_3s):
    out = tmp_path / "out.mp4"
    add_audio(str(video_10s), audio_path=str(audio_3s), output_path=str(out))  # no policy => default
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.1   # outro NOT eaten

def test_shortest_policy_warns_and_shortens(tmp_path, video_10s, audio_3s):
    out = tmp_path / "s.mp4"
    res = add_audio(str(video_10s), audio_path=str(audio_3s), duration_policy="shortest", output_path=str(out))
    assert _get_video_duration(str(out)) < 4.0
    assert any("duration" in w.lower() for w in res["warnings"])
```

- [ ] **Step 2: RED** — `python3 -m pytest -q tests/test_add_audio_duration_policy.py::test_keep_video_default_preserves_outro` → fails (current engine can shorten to audio length / lacks policy kwarg).

- [ ] **Step 3: Implement** the `duration_policy` enum: `keep_video` (default) pads/holds video's full duration (audio padded with silence or looped only under explicit `loop_audio`/`pad_audio`); `trim_audio` trims audio to video; `shortest` reproduces legacy `-shortest`/`amix=...:duration=shortest` and appends a duration-change warning. Never change mix-mode default silently. Escape any user value; keep the existing signature backward-compatible (new kwarg only).

- [ ] **Step 4: Green (fixture family)** — `python3 -m pytest -q tests/test_add_audio_duration_policy.py` covering shorter/longer/equal audio, silent source, multi-stream.

- [ ] **Step 5: Commit** — `git commit -m "fix(audio): loss-proof add-audio duration policy"`.

### Task 2: Surface parity + receipt evidence

**Files:** Modify `kinocut/server_tools_basic.py`, `kinocut/client/audio.py`, `kinocut/cli/handlers_audio.py`, CLI parser; Test extends `tests/test_add_audio_duration_policy.py` + surface tests.

- [ ] **Step 1: Failing parity test** — MCP `video_add_audio(..., duration_policy="keep_video")`, Python `Client().add_audio(..., duration_policy=...)`, CLI `--duration-policy keep_video` all reach the engine; omitting the flag preserves the safe default; the `ai_video` receipt section records `duration_policy` and any warning.
- [ ] **Step 2: RED** → **Step 3: Implement** additive param across surfaces; write the `duration_policy` + preservation warning into the receipt via `attach_ai_video_section` (Plan 00).
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_add_audio_duration_policy.py tests/test_server.py tests/test_client.py tests/test_cli_handlers.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(audio): expose duration policy across mcp/cli/python with receipt evidence"`.

---

## PR 1.2 — ASS and dimension-aware subtitle burn (#27, #31–32)

### Task 3: Shared EOF-clamp utility + failing tests

**Files:** Create `kinocut/subtitles_eof.py`; Test `tests/test_subtitles_ass_and_dimension.py`.

- [ ] **Step 1: Failing test** — `clamp_segments_to_eof([(0,5),(5,999)], eof_seconds=8.0)` yields `[(0,5),(5,8)]` and flags a clamp warning; used by generate/burn/ASR.
- [ ] **Step 2: RED** → **Step 3: Implement** the pure utility (no FFmpeg). Reused later by Plan 02 PR 4.2 and PR 5.1.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_subtitles_ass_and_dimension.py -k eof`.
- [ ] **Step 5: Commit** — `git commit -m "feat(subtitles): shared EOF clamp utility"`.

### Task 4: ASS input + dimension-aware SRT/VTT render

**Files:** Modify `kinocut/engine_subtitles.py`, `kinocut/server_tools_media.py`, client/CLI subtitle surfaces; Test `tests/test_subtitles_ass_and_dimension.py`.

**Interfaces:** Consumes `subtitles(input_path, subtitle_path, output_path, style=...)` (engine_subtitles.py:21), `_run_ffprobe_json` for display dimensions, `_escape_ffmpeg_filter_value`.

- [ ] **Step 1: Failing tests**

```python
def test_authored_ass_styles_preserved(tmp_path, vertical_video, authored_ass):
    out = subtitles(str(vertical_video), str(authored_ass), output_path=str(tmp_path/"a.mp4"))
    # burned output keeps the ASS PlayRes / position (assert via probe or pixel sample region)
    assert out is not None

def test_srt_render_is_dimension_aware(tmp_path, vertical_video, srt_file):
    subtitles(str(vertical_video), str(srt_file), output_path=str(tmp_path/"v.mp4"))
    # ASS synthesized with actual display dimensions, not libass 384x288 default
```

- [ ] **Step 2: RED** → **Step 3: Implement**: accept `.ass` input and pass it through libass preserving authored styles/positions/PlayRes; for SRT/VTT probe real display width/height and synthesize safe ASS render settings (PlayResX/Y = display dims). Escape all user style/path values. Keep SRT/VTT behavior backward-compatible where dimensions match.
- [ ] **Step 4: Green (fixture family)** — vertical/horizontal/square × SRT/VTT/ASS, authored positions/PlayRes.
- [ ] **Step 5: Surface parity + commit** — `python3 -m pytest -q tests/test_subtitles_ass_and_dimension.py tests/test_server.py tests/test_client.py && git commit -m "feat(subtitles): ASS support and dimension-aware SRT/VTT render"`.

---

## PR 2.1 — Ingest, immutable originals, unified preflight (#2–4, #36/#38 supply)

### Task 5: Project ingest facade with generation metadata + rights

**Files:** Create `kinocut/aivideo/ingest.py`; Test `tests/test_aivideo_ingest.py`.

**Interfaces:** Consumes `kinocut/projectstore/ingest.py:ingest_asset` (Plan 00), `kinocut/contracts/asset.py` (`AssetRecord`, `GenerationLineage`).

- [ ] **Step 1: Failing test** — ingest copies bytes into the content-addressed store before any normalization; re-ingest is idempotent by digest; generation metadata (model/provider/prompt-hash/settings-hash) and rights status are recorded on the `AssetRecord`; the original is never mutated.
- [ ] **Step 2: RED** → **Step 3: Implement** the facade; rights status defaults to `unverified` with a private evidence reference; lineage links source/reference asset IDs.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_aivideo_ingest.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): project ingest with generation metadata and rights"`.

### Task 6: Unified preflight report

**Files:** Create `kinocut/aivideo/preflight.py`; Test `tests/test_aivideo_preflight.py`.

**Interfaces:** Consumes `kinocut/engine_probe.py`, `VisualQualityGuardrails.check_audio_levels` (quality_guardrails.py:535) + `_analyze_loudnorm` (:240), integrity decode.

- [ ] **Step 1: Failing test** — `PreflightReport` composes technical (streams, codecs, dimensions, fps, rotation), loudness (integrated LUFS/true-peak), color, and integrity (full-decode) into one artifact; missing audio yields explicit `has_audio=False`, never a zero-loudness lie.
- [ ] **Step 2: RED** → **Step 3: Implement** the composed report; store as a preflight artifact referenced by `AssetRecord.preflight_artifact_id`.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_aivideo_preflight.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(aivideo): unified media preflight report"`.

---

## PR 2.2 — Temporal evidence package (#9–12)

### Task 7: Motion strip, late-frame sampler, region crops, manifest

**Files:** Create `kinocut/aivideo/inspection/{motion_strip,samplers,manifest}.py`; Test `tests/test_inspection_motion_strip.py`, `tests/test_inspection_samplers.py`, `tests/test_inspection_manifest.py`.

**Interfaces:** Consumes `engine_storyboard.py`, `engine_frames.py`, `_run_ffprobe_json`.

- [ ] **Step 1: Failing tests** — motion strip samples the full playable duration and includes the last decodable frame; default temporal percentages are exactly `[0, 25, 50, 75, 95, last]`; declared text/logo region crops are normalized coords, extracted at source resolution, and carry the sampled timestamp; `InspectionPackage` manifest lists any missing optional analyzer as an unavailable capability (never silently omitted).
- [ ] **Step 2: RED** → **Step 3: Implement** deterministic tiled strip + samplers + manifest (design §4.8, §5.2). Manifest is deterministic for the same referenced artifacts; media bytes are not claimed deterministic across FFmpeg builds.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_inspection_motion_strip.py tests/test_inspection_samplers.py tests/test_inspection_manifest.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(inspection): temporal evidence package"`.

---

## PR 2.3 — Deterministic temporal defect checks (#13–14, deterministic part of #16)

### Task 8: Loop integrity + black/frozen/duplicate/corrupt intervals

**Files:** Create `kinocut/aivideo/inspection/temporal_checks.py`; Test `tests/test_inspection_temporal_checks.py`.

**Interfaces:** Extends `VisualQualityGuardrails.check_motion`/`_measure_temporal_motion` (quality_guardrails.py:754/677), `check_brightness` (:373), integrity decode.

- [ ] **Step 1: Failing tests** — loop-integrity emits an opening/closing frame-difference metric + finding with thresholds; black/frozen/duplicate/corrupt segments are reported as bounded time intervals as `DefectFinding`s with the correct taxonomy codes (`black frames`, `frozen frames`, `broken loop`, `corrupt frames`) and `status="suspected"`.
- [ ] **Step 2: RED** → **Step 3: Implement** deterministic detectors; no ML. Note the coverage probe found no dedicated duplicate-frame function today — add one here as a bounded frame-diff interval detector.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_inspection_temporal_checks.py` with late-text-drift/broken-loop/black/frozen/duplicate/corrupt fixtures.
- [ ] **Step 5: Commit** — `git commit -m "feat(inspection): deterministic temporal defect checks"`.

---

## PR 2.4 — Optional visual findings providers (#15–16)

### Task 9: Capability-gated motion-intent + generative-defect analyzers

**Files:** Create `kinocut/aivideo/inspection/providers.py`; Test `tests/test_inspection_providers.py`. May consume `kinocut/visual_intelligence/` if present.

- [ ] **Step 1: Failing tests** — when the optional provider is absent, the analyzer returns a typed `capability_unavailable` finding and the deterministic package remains complete; when present, it proposes timestamped `DefectFinding`s that stay `suspected` until a human decision.
- [ ] **Step 2: RED** → **Step 3: Implement** capability gating over the shared inspection artifacts; provider absence never blocks deterministic artifact generation (design §9).
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_inspection_providers.py` (mock provider present + absent).
- [ ] **Step 5: Commit** — `git commit -m "feat(inspection): optional visual findings providers"`.

### Task 10: Inspection surfaces + full-suite gate

**Files:** MCP/CLI/Python for `video_ingest`, `video_preflight`, `video_inspect_temporal`; Test `tests/test_inspection_surfaces.py`.

- [ ] **Step 1: Failing parity tests** for all three surfaces (MCP result shape, Python client, CLI handler + exit code).
- [ ] **Step 2: RED** → **Step 3: Implement** using the `@mcp.tool()` + `@_safe_tool` + `_result` pattern (server_app.py:39/117) and `CommandRunner.register` (cli/runner.py:20).
- [ ] **Step 4: Full gate** — `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo`.
- [ ] **Step 5: Leak audit + commit** — `git commit -m "feat(inspection): mcp/cli/python surfaces for ingest, preflight, temporal inspect"`.

---

## Wave 1–2 completion criteria

- Add-audio eaten-outro regression is green with `keep_video` default; `shortest` warns. Subtitles accept ASS and render dimension-aware; EOF clamp shared utility in place.
- Ingest is content-addressed + idempotent; preflight is one composed report; temporal inspection produces a deterministic package with an explicit unavailable-capability list.
- All fixture families from design §8 relevant to audio-duration, subtitles, and temporal defects are exercised with real FFmpeg.
- MCP + Python + CLI parity + backward fixtures green; full suite green; canonical import assertion passes; Ruff clean; modules ≤ 800 LOC.
- Independent review approved; no self-approval; no release actions (index §3.6).
- Downstream: Plan 02 (Wave 3 verdicts/salvage) consumes these `DefectFinding`s, `AssetRecord`s, and inspection artifacts.
