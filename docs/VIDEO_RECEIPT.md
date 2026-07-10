# Video Receipt

A Video Receipt is the trust artifact for an agentic media workflow. It records what the user asked for, what media was inspected, which tools ran, what changed, which guardrails fired, and what still needs human review.

Use it when a workflow creates or edits media that may be published, handed to a client, or used as proof.

## Required Fields

```json
{
  "user_intent": "Turn a source clip into a captioned vertical short.",
  "source_media": {
    "path": "output/source.mp4",
    "duration_seconds": 6.0,
    "width": 1280,
    "height": 720
  },
  "tool_calls": [
    {
      "stage": "01-trim",
      "tool": "Client.trim",
      "output": "output/01_trimmed.mp4"
    }
  ],
  "edits_applied": [
    "trimmed source clip",
    "resized to 9:16",
    "added hook text",
    "normalized audio",
    "exported final MP4"
  ],
  "guardrails_triggered": [],
  "quality": {
    "all_passed": true,
    "overall_score": 70.3,
    "recommendations": []
  },
  "review_artifacts": {
    "final_video": "output/final_clip.mp4",
    "thumbnail": "output/checkpoint/thumbnail.jpg",
    "storyboard": [
      "output/checkpoint/storyboard/frame_01.jpg",
      "output/checkpoint/storyboard/frame_02.jpg"
    ]
  },
  "human_review": {
    "required": true,
    "status": "pending",
    "instructions": "Open the final video, thumbnail, and storyboard before publishing."
  },
  "known_limitations": [
    "Automated quality checks do not replace visual/audio review."
  ],
  "next_edit_suggestion": "Adjust hook text and rerun release checkpoint after human review."
}
```

## Trust Rules

- Do not treat a rendered video as publishable until a receipt exists.
- Do not hide quality warnings. Warnings are part of the proof.
- Do not overwrite source media.
- Do not mark human review complete automatically.
- Keep generated videos, thumbnails, and storyboards out of git unless they are intentionally curated release/demo assets.

## Local Verification

Use the confidence benchmark to check that a workflow produced the expected receipt and review artifacts:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_confidence_benchmark.py
```

The benchmark is intentionally narrow: it proves the receipt-backed baseline can run and that the final video, quality report, release checkpoint, thumbnail, storyboard frames, and human-review state are present.

---

# Workflow-engine + compositor receipt kinds

Beyond the release-checkpoint Video Receipt above, the workflow engine and the compositor
emit machine-readable provenance artifacts. Every one carries a `receipt_kind`
discriminator so an inspecting agent can tell them apart, and `video_workflow_inspect`
reads all of them (see [WORKFLOWS.md](WORKFLOWS.md)).

| `receipt_kind` | Emitted by | Shape |
|---|---|---|
| `workflow` | `video_workflow_render` | Multi-step render: per-step status + hashes, resume cursor, cleanup manifest. |
| `workflow_plan` | `video_workflow_plan` | Dry-run plan: op graph + source probes/hashes, no rendered media. |
| `workflow_batch` | `video_workflow_render(all_variants=True)` | Summary wrapping one `workflow` receipt per variant. |
| `layer_plan` | `video_composite_layers` | Single-render compositor plan/receipt (v2). |

## `schema_version` policy

`schema_version` is a **write-only** field — no consumer branches on it, so it increments
on **additive expansion** and a bumped version stays **backward-readable** (existing
readers of known fields keep working). The `layer_plan` receipt is now `schema_version: 2`
(rotation/pivot/blend fields added additively over v1); the workflow receipts are
`schema_version: 1`.

## `receipt_kind` discriminator + legacy inference

A pre-bump `layer_plan` receipt in the wild is `schema_version: 1` with **no**
`receipt_kind` field. `video_workflow_inspect` tolerates this: when `receipt_kind` is
absent it **infers** the kind from the `tool` field (`video_composite_layers` →
`layer_plan`, `video_workflow_render` → `workflow`, `video_workflow_plan` →
`workflow_plan`), defaulting to `layer_plan` when neither is present, and flags the
inference under `human_review`. The kind is never hardcoded to a `schema_version`, so a
future bump is handled gracefully.

## `workflow` receipt (`receipt_kind: "workflow"`, `schema_version: 1`)

Emitted by `video_workflow_render`. Hashes are integrity checks on persisted files, never
byte-determinism claims. Paths are workspace-relative. (Hashes abbreviated below.)

```json
{
  "schema_version": 1,
  "receipt_kind": "workflow",
  "tool": "video_workflow_render",
  "versions": { "mcp_video": "1.6.0", "ffmpeg": "8.1" },
  "spec_hash": "sha256:be2f3a9b...",
  "workflow": { "name": "captioned-vertical-short", "variant": null },
  "sources": [
    { "id": "hero", "resolved": "input/hero.mp4", "source_hash": "sha256:3b976d49...",
      "probe": { "duration": 8.0, "resolution": "320x240", "codec": "h264" } }
  ],
  "steps": [
    { "id": "probe-hero", "op": "probe", "status": "completed",
      "inputs": { "src": "@sources.hero" }, "input_hashes": { "src": "sha256:3b976d49..." },
      "output": null, "output_hash": null,
      "started_at": "2026-07-09T09:02:15.965980+00:00", "ended_at": "2026-07-09T09:02:15.966141+00:00" },
    { "id": "trim-hero", "op": "trim", "status": "completed",
      "inputs": { "src": "@sources.hero" }, "input_hashes": { "src": "sha256:3b976d49..." },
      "output": "work/be2f3a9b-2effedb3/mcp_video_hero_trim.mp4", "output_hash": "sha256:00727499...",
      "started_at": "...", "ended_at": "..." },
    { "id": "caption", "op": "add_text", "status": "completed",
      "inputs": { "src": "@work/hero_vertical.mp4" }, "input_hashes": { "src": "sha256:5a596ffe..." },
      "output": "output/final.mp4", "output_hash": "sha256:8633ad2a...",
      "started_at": "...", "ended_at": "..." }
  ],
  "outputs": [ { "id": "master", "path": "output/final.mp4", "output_hash": "sha256:8633ad2a..." } ],
  "work_dir": "work/be2f3a9b-2effedb3",
  "cleanup_manifest": {
    "intermediates": ["work/be2f3a9b-2effedb3/mcp_video_hero_trim.mp4", "work/be2f3a9b-2effedb3/mcp_video_hero_vertical.mp4"],
    "cleaned": true, "policy": "clean-on-success"
  },
  "resume_cursor": { "last_completed_step": "caption", "next_step": null },
  "feature_flags": { "variants": true, "resume_used": false, "resumed_from": null, "ops": ["probe", "trim", "resize", "add_text"] },
  "warnings": [],
  "status": "completed",
  "render_determinism_scope": "spec/input/output hashes are deterministic; rendered bytes may vary across FFmpeg builds"
}
```

- Per-step and overall `status`: `pending | running | completed | failed | skipped`.
- On failure, the failed step records a sanitized `error` (`code`, `type`, workspace-
  relative `message`, `suggested_action`), later steps are `pending`, `resume_cursor.next_step`
  points at the failed step, intermediates are kept (`cleaned: false`), and overall `status`
  is `failed`.
- On resume, a reused step keeps `status: "completed"` and adds `"skipped": true`;
  `feature_flags.resume_used` becomes `true` and `resumed_from` names the resume point.
- `output_hash` is `null` until the step's output exists (mirrors `probe`, which produces
  none).

## `workflow_plan` artifact (`receipt_kind: "workflow_plan"`)

Emitted by `video_workflow_plan`. Same field vocabulary as the render receipt but renders
zero media: every step `status` is `pending`, `output_hash` is `null`, sources are probed
and hashed where they exist, and a `warnings` list flags non-structural runtime concerns
(e.g. `source_missing`). Includes `versions` and `spec_hash`.

## `workflow_batch` summary (`receipt_kind: "workflow_batch"`)

Emitted by `video_workflow_render(all_variants=True)`. Wraps one `workflow` receipt per
variant with no cross-variant leakage:

```json
{
  "schema_version": 1,
  "receipt_kind": "workflow_batch",
  "tool": "video_workflow_render",
  "versions": { "mcp_video": "1.6.0", "ffmpeg": "8.1" },
  "spec_hash": "sha256:be2f3a9b...",
  "workflow": { "name": "captioned-vertical-short", "variant": null },
  "count": 1,
  "variants": [ { "receipt_kind": "workflow", "workflow": { "name": "...", "variant": "square" }, "status": "completed" } ],
  "status": "completed"
}
```

## `layer_plan` receipt v2 (`receipt_kind: "layer_plan"`, `schema_version: 2`)

Emitted by `video_composite_layers` (dry-run plan or render receipt). v2 adds
`transform.rotation` + `transform.pivot` (null when rotation is unused), a `features.rotation`
flag, and `features.blend_modes` may now contain the five full-canvas blend modes —
`features.blend_modes` lists the modes **used in the spec** (including `normal`), not the
catalog. Audio is dropped (`audio_policy: "dropped_video_only"`, `features.audio:
"dropped"`).

```json
{
  "schema_version": 2,
  "receipt_kind": "layer_plan",
  "tool": "video_composite_layers",
  "spec_hash": "sha256:24ad4ddd...",
  "canvas": { "width": 640, "height": 360, "fps": 12.0, "duration": 2.0, "background": "#000000" },
  "layers": [
    { "id": "bg", "type": "video", "resolved_src": "bg.mp4", "source_hash": "sha256:34ae6b4c...",
      "opacity": 1.0, "position": { "x": 0.0, "y": 0.0 }, "blend": "normal",
      "transform": { "width": null, "height": null, "scale": null, "rotation": null, "pivot": null },
      "timing": { "start": null, "duration": null }, "mask": null, "mask_hash": null,
      "color": null, "input_index": 1, "mask_input_index": null },
    { "id": "tint", "type": "image", "resolved_src": "tint.png", "source_hash": "sha256:345a53b7...",
      "opacity": 1.0, "position": { "x": 0.0, "y": 0.0 }, "blend": "multiply",
      "transform": { "width": null, "height": null, "scale": null, "rotation": null, "pivot": null },
      "timing": { "start": null, "duration": null }, "mask": null, "mask_hash": null,
      "color": null, "input_index": 2, "mask_input_index": null },
    { "id": "logo", "type": "image", "resolved_src": "logo.png", "source_hash": "sha256:8090fd20...",
      "opacity": 0.9, "position": { "x": 320.0, "y": 180.0 }, "blend": "normal",
      "transform": { "width": null, "height": null, "scale": null, "rotation": 15.0, "pivot": "center" },
      "timing": { "start": null, "duration": null }, "mask": null, "mask_hash": null,
      "color": null, "input_index": 3, "mask_input_index": null }
  ],
  "filtergraph_hash": "sha256:25eb30b9...",
  "output_path": "output/composite.mp4",
  "output_hash": null,
  "audio_policy": "dropped_video_only",
  "features": {
    "layer_types": ["image", "video"], "transforms": false, "rotation": true,
    "timing_windows": false, "masks": false, "blend_modes": ["multiply", "normal"], "audio": "dropped"
  },
  "render_determinism_scope": "input/spec/filtergraph/output hashes are deterministic; rendered bytes may still vary across FFmpeg builds"
}
```

> `output_path`, `resolved_src`, and `mask` are recorded **relative to the spec
> directory** whenever the file lives inside it (the common workspace case), and stay
> absolute only for a path the spec explicitly points outside that directory. Internal
> rendering always uses the resolved absolute location; only the receipt is relativized.
> Keep committed example receipts relative and free of home paths, usernames, or tokens.
