# Insta360 X4 — 360 dual-cam assembly

**Status (2026-08-13):** Implemented on `master` (`a17387a`). Operator guide: [`docs/360_ASSEMBLY.md`](../../360_ASSEMBLY.md). Not in pip 1.13.4.

**Status:** Draft for user review (do not implement until approved)  
**Date:** 2026-08-13  
**Tip:** `eac1432` · Kinocut 1.13.4 · 196 MCP / 167 CLI  
**Input assumption:** stitched 360 MP4 exported from Insta360 Studio/app. Not `.insv`.

## Summary

Treat one X4 360 file as **two or more virtual cameras**, propose an assembly plan, let a human or agent approve it, then render a normal 16:9 or 9:16 video with existing FFmpeg seams.

Flagship jobs:

1. **Desk / build-in-public** — one lens on the coder, one on the screens. Split, PiP, or switch.
2. **Tarot / table** — talent talking/shuffling plus the cards/table. Same assembly.

A **pluggable director** (local or cloud VLM) may *write* the plan. Kinocut always *formats, validates, renders, QC, and receipts*. The model never writes pixels.

## Product decisions (locked)

1. **One plan schema, three writers:** `heuristic` (presets), `single` (best one look), `model` (VLM/agent JSON).
2. **Layouts are free:** `single` | `split` | `pip` | `switch`. Defaults: desk → split, table → switch. Caller may override.
3. **Storyboard then approve then render.** No silent publish.
4. **VLM is a plug.** Local first (Ollama / any OpenAI-compatible localhost). Cloud only with explicit opt-in. Swap by id, not a rebuild.
5. **Kinocut owns format.** `v360` extract + existing `composite-layers` / trim+merge + `assert_quality`.
6. **No 197th MCP name** unless a param on `video_intent` cannot carry the plan. Prefer `goal=` / existing review+render.
7. **`.insv` is out.** Fail closed with “export a stitched 360 MP4 from Insta360 first.”
8. **Do not stitch, do not face-orbit, do not restaff Phase 4 generative execute.** Director proposes a plan only.

## Problem

X4 already recorded both hemispheres. Today Kinocut has no spherical path: `reframe` is a 2D crop, `storyboard` samples a flat timeline, and `video_qc_vision` only sniffs Anthropic (`auto_scored: False`). An agent cannot turn “me + screens” or “me + cards” into a watchable two-cam edit without knowing yaw/pitch.

Consumer Studio can reframe by hand. Kinocut’s job is an **inspectable, swappable-director, fail-closed assembly** that an agent can run.

## Goals

- Detect a stitched equirect source (2:1 and/or spherical metadata).
- Emit named virtual cameras (`talent`, `screens`, `table`, plus custom yaw/pitch/fov).
- Produce a storyboard of candidate stills per camera.
- Write / validate / approve a 360 assembly plan.
- Render approved plans to 16:9 or 9:16.
- Let a director adapter propose the plan; never require one.
- Name the writer on the receipt (`heuristic`, `ollama/<model>`, `openai/<model>`, …).

## Non-goals

- Insta360 `.insv` decode or official SDK stitch.
- Continuous auto-steer around the sphere (later).
- Hardcoding Anthropic/OpenAI as *the* director.
- Silent cloud fallback when a local director is missing.
- New public MCP/CLI verb unless existing surfaces cannot carry the artifact.
- Claiming “cinematic AI director” in README/`public_claims.json`.

## Architecture

```
stitched 360 MP4
    → probe (equirect? spherical metadata? aspect ~2:1)
    → cameras (preset and/or custom)
    → sample stills (v360 at t_i × camera)
    → plan writer: heuristic | single | director adapter | human JSON
    → validate plan schema
    → storyboard + review (approve / reject / edit layout)
    → render: v360 clips → split | pip | switch | single
    → QC + receipt (source hash, cameras, layout, writer)
```

Reuse, do not rebuild:

| Seam | Use |
|------|-----|
| `ffmpeg` `v360` | Rectilinear extract from equirect |
| `composite-layers` | Split and PiP |
| trim + merge | Switch cuts |
| shorts review / EDL approval | Approve candidate ids / layout |
| `storyboard` / `thumbnail` | Human-visible stills |
| `assert_quality` | Ship seam (default 80) |
| `video_intent` `goal=` | “desk 360 split 9:16” → plan, not a tool list |
| remote `ProviderAdapter` rule | Adapter must not mutate an approved plan |

## Plan schema (contract)

Artifact kind: `360_assembly_plan`. Frozen JSON. Invalid plan → `MCPVideoError` `validation_error`.

```json
{
  "artifact_kind": "360_assembly_plan",
  "schema_version": 1,
  "source": { "path": "media/x4.mp4", "sha256": "sha256:…", "width": 5760, "height": 2880, "duration_seconds": 120.0 },
  "projection": "equirect",
  "output": { "aspect": "9:16", "width": 1080, "height": 1920 },
  "cameras": [
    { "id": "talent", "yaw": 0, "pitch": 0, "roll": 0, "fov": 90 },
    { "id": "screens", "yaw": 180, "pitch": 0, "roll": 0, "fov": 90 }
  ],
  "layout": "split",
  "windows": [
    { "id": "w1", "start": 0.0, "end": 120.0, "cameras": ["screens", "talent"], "layout": "split" }
  ],
  "writer": { "kind": "heuristic", "provider": null, "model": null },
  "status": "proposed"
}
```

`status`: `proposed` → `approved` | `rejected`. Render requires `approved`.

`layout` on a window overrides the plan default so a switch sequence can mix single + split.

Presets:

| Preset | Cameras | Default layout |
|--------|---------|----------------|
| `desk` | `talent` yaw=0, `screens` yaw=180 | `split` |
| `table` | `talent` yaw=0 pitch=0, `table` yaw=180 pitch=-35 | `switch` |

Caller may pass explicit cameras and ignore presets.

## Director adapter (the plug)

```
propose(stills, cameras, duration, output) -> 360_assembly_plan | capability_unavailable
```

- **Local first:** `ollama`, `lmstudio`, any OpenAI-compatible `base_url` on localhost.
- **Cloud:** `openai`, `anthropic`, `gemini`, `openrouter` — only if `allow_cloud=true` (or equivalent explicit flag). No vendor hop if the chosen one is down.
- **None:** heuristic/single still work.
- Select with `KINOCUT_360_DIRECTOR=<id>` and optional `KINOCUT_360_DIRECTOR_MODEL=…` plus `KINOCUT_360_DIRECTOR_BASE_URL=…`. CLI/MCP/Client pass the same fields.
- A backend that returns non-schema JSON is `capability_unavailable`, not a guessed cut.
- After approve, render **must not** call the director. Same rule as `kinocut/remote/adapters.py`: mapping cannot change the approved plan.

Do **not** extend `watching/vision_qc.py`’s Anthropic sniff for this. New small module (e.g. `kinocut/te/sphere_director.py` + `kinocut/te/sphere_plan.py`). Keep functions ≤80, modules ≤800.

## Surfaces (no catalog growth)

| Step | Existing surface | Behavior |
|------|------------------|----------|
| Propose | `video_intent` `goal="desk 360 split 9:16"` or Client/CLI flag on an existing inspect/plan verb | Writes `360_assembly_plan` + storyboard dir |
| Review | `video_review_decide` / shorts-review pattern | `approve` / `reject` / layout override |
| Render | `video_cutfile_render` or workflow compile of approved plan | `v360` + composite/merge |
| Doctor | `kino doctor` | Lists director backends like TTS (`detect_tts_backend`) |

If a param cannot land without a new public name, stop and ask — do not silently add tool 197.

## Error handling

| Case | Error |
|------|-------|
| `.insv` or non-equirect | `InputFileError` / `validation_error` `not_360_equirect` |
| Missing FFmpeg `v360` | `ProcessingError` with timeout + truncated stderr |
| Director unset / down | plan still emitted by heuristic; director field `unavailable` |
| Cloud without opt-in | `validation_error` `cloud_execution_denied` |
| Render without approve | `validation_error` `human_apply_required` |
| User strings in filters | `_escape_ffmpeg_filter_value` |

## Testing

- Synthetic 2:1 color bars (left/right hemispheres different colors) → desk extract shows two distinct frames.
- Plan schema reject: missing cameras, end≤start, unknown layout.
- Heuristic desk/table defaults.
- Director fake adapter returns valid plan; bad JSON → unavailable.
- Cloud flag off → denied even if key present.
- Approve then render writes a file; no approve → error.
- Identity: `kinocut.Client is mcp_video.Client` still holds.
- No `published_*` bump. 196/167 pins stay green.

## v1 vs later

**v1:** probe, presets, storyboard, plan schema, heuristic + single, one local OpenAI-compatible director + one cloud adapter behind opt-in, approve, render split/pip/switch/single.

**Later:** continuous steer, subject tracking around the sphere, more vendors as extra adapter files, `.insv` only if Insta360 publishes a local stitch CLI.

## Risks

| Risk | Mitigation |
|------|------------|
| “AI editor” claim | Receipt writer field; README stays honest |
| Vendor lock | Adapter id + schema; no SDK in the render path |
| Huge X4 files | Sample stills first; do not decode the whole sphere twice |
| 197th tool | Existing intent/review/render only |
| Model writes a pretty but invalid cut | Schema validate; fall back to heuristic, do not render |

## Next

1. User reviews this spec.
2. If approved: implementation plan (small TDD tasks) then one PR.
3. If not: revise this file, do not start code.
