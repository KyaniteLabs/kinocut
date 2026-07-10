# Architectural verdict

At the pre-rename audit snapshot, Kinocut (then named `mcp-video`) was a guardrailed media RPC toolbox, not yet an agentic editor.

The snapshot's 119 tools provided strong typed operations, validation, FFmpeg safety, quality gates, and broad feature coverage. The missing layer remains a durable editing kernel: projects, revisioned timelines, render jobs, content-addressed artifacts, and machine-driven review loops. The release-cutover surface is now 135 tools.

The next architectural move is not another tool. Freeze the existing tools as compatibility adapters over five foundational primitives.

## Ranked synthesis

| Rank | Architectural gap | Confidence | Consequence |
|---:|---|---|---|
| 1 | No durable project/revision state | High | Agents cannot inspect, modify, branch, undo, or resume an edit reliably. |
| 2 | Timeline is a one-shot render DTO, not an editing object model | High | Every change requires regenerating and rerendering a monolithic JSON specification. |
| 3 | No asynchronous render execution plane | High | Long renders block tool calls; cancellation, recovery, scheduling, and remote execution are impossible. |
| 4 | No content-addressed media/artifact plane | High | Identical work is repeated, proxies are disconnected files, and provenance depends on mutable paths. |
| 5 | Quality checks are terminal tools, not an event-driven control loop | High | The system can diagnose output but cannot autonomously observe, propose a patch, rerender, and compare. |

## 1. Missing architectural primitives

### Durable edit projects

The current “project” abstraction scaffolds cinematic planning files or represents a Hyperframes directory. Neither owns a complete edit.

A real project must persist:

- Stable project, asset, sequence, track, clip, effect, and artifact IDs.
- Media references and fingerprints.
- Timeline head and revision branches.
- Render profiles, guardrail policies, review decisions, and provenance.
- Jobs that survive MCP client disconnection or server restart.

The canonical unit of work must become `project_id + revision_id`, not `input_path + output_path`.

### Real timeline intermediate representation

The existing `Timeline` model contains tracks and clips, but it is a render request schema, not an editable graph. It has no stable node IDs, rational timebase, keyframes, nested sequences, effect stack, generators, linked audio/video, gaps, track state, or mutation operations. See [models.py](../../../kinocut/models.py#L310).

Its executor exposes deeper limitations:

- Video clips from every video track are flattened into one list.
- `TimelineClip.start` affects audio placement but not video placement.
- `Timeline.duration` is defined but unused.
- Transitions are reduced to a list of types plus the first transition’s duration.
- Trim, merge, composite, audio, resize, and export form a sequential re-encode pipeline.
- Temporary state is deleted after every invocation.

See [engine_timeline.py](../../../kinocut/engine_timeline.py#L38) and [engine_timeline.py](../../../kinocut/engine_timeline.py#L106).

The future timeline must be a typed, immutable graph that compiles into a render DAG.

### Non-destructive revision DAG

There is no transaction, revision, parent revision, branch, undo, redo, diff, or checkout abstraction.

Every agent mutation must:

1. Target an explicit base revision.
2. Apply typed operations atomically.
3. Produce a new immutable revision.
4. Preserve the previous revision.
5. Return a semantic diff and validation report.

Undo becomes revision checkout or revert. Alternate edits become branches. Concurrent agents use compare-and-swap against `base_revision_id`, preventing silent lost updates.

### Render graph and asynchronous jobs

The pre-rename live inspection found 119 registered tools:

- 118 synchronous tools.
- One asynchronous tool: `video_convert`.
- Zero tools accepting `job_id`, `session_id`, or callbacks/hooks.
- 74 tools accepting `input_path`.
- 75 tools accepting `output_path`.

Even progress-enabled FFmpeg execution blocks on `proc.wait()` until completion; progress is notification plumbing, not asynchronous job execution. See [ffmpeg_helpers.py](../../../kinocut/ffmpeg_helpers.py#L232) and [server_app.py](../../../kinocut/server_app.py#L82).

A render must become a persistent DAG job with:

- Immediate submission response.
- Stage and node-level progress.
- Cancellation and retry.
- Resumption after process failure.
- Partial-range rendering.
- Progressive segment publication.
- Local or remote worker leasing.
- Deterministic reuse of completed nodes.

Hyperframes’ `workers` parameter is intra-render local parallelism, not a distributed worker architecture.

### Content-addressed media and proxy store

The only general cache is an in-memory ffprobe cache keyed by path, modification time, and size. It disappears on restart and cannot reuse derived media. See [engine_probe.py](../../../kinocut/engine_probe.py#L16).

A media store must assign immutable IDs to:

- Source assets.
- Low-resolution proxies.
- Transcripts, waveforms, scene maps, and embeddings.
- Render graph nodes.
- Frames, segments, previews, and final exports.
- Quality reports and review findings.

Cache identity must include source digest, normalized operation parameters, timeline-node hash, renderer/toolchain version, and output profile.

The current `video_preview` is useful but produces another ordinary output file. It is not a managed proxy tied to an asset or revision. See [engine_preview.py](../../../kinocut/engine_preview.py#L14).

### Event and review control plane

The current release checkpoint runs quality analysis, emits thumbnail/storyboard artifacts, and instructs a human to inspect them. See [server_tools_ai.py](../../../kinocut/server_tools_ai.py#L256).

That is a checkpoint, not a feedback loop. The missing event system needs typed events such as:

- `timeline.revision.created`
- `render.node.completed`
- `render.segment.ready`
- `render.completed`
- `quality.gate.failed`
- `review.finding.created`
- `review.patch.proposed`
- `review.patch.accepted`

A VLM reviewer must consume proxies, storyboards, audio features, transcript, project objective, and timeline diff; return findings anchored to time ranges and timeline node IDs; then propose typed timeline mutations. It must never mutate project head invisibly.

## 2. Current design decisions that will not scale

| Current decision | Why it fails |
|---|---|
| One top-level tool per media verb | Tool count grows combinatorially as operations gain scheduling, ranges, revisions, proxies, policies, and distributed execution. |
| Filesystem path as identity | Paths are mutable, machine-specific, collision-prone, and meaningless to remote workers. |
| Tool call equals render execution | The client must remain connected while expensive work runs; there is no cancellation, recovery, queueing, or admission control. |
| `EditResult` centers on `output_path` | It lacks artifact ID, revision ID, job ID, content digest, parent provenance, cache status, and renderer fingerprint. See [models.py](../../../kinocut/models.py#L96). |
| Timeline passed inline as dict/string/file | It has no server-owned canonical state, atomic patch protocol, or concurrency protection. See [server_tools_media.py](../../../kinocut/server_tools_media.py#L458). |
| Sequential intermediate-file chaining | It causes redundant decoding/encoding and cannot invalidate or reuse individual graph nodes. |
| Manual intermediate cleanup | Garbage collection is filename/suffix-oriented rather than reachability- and retention-policy-driven. |
| Preview as standalone transformation | It cannot incrementally update only the changed timeline range or share cached analysis with final rendering. |
| Progress as percentage callback | A percentage cannot represent graph stages, retries, worker ownership, partial artifacts, or stalled nodes. |
| Quality gate after rendering | It detects problems late and has no structured path back to the responsible timeline nodes. |
| Human-review instruction embedded in result | It cannot trigger VLM review, approval policy, automatic safe fixes, or bounded iteration. |
| Hyperframes as a separate project island | Hyperframes compositions, FFmpeg edits, and repurposing outputs do not share one project graph, asset store, revision history, or job system. |
| Stdio-local execution as the implicit runtime | Remote workers require authenticated artifact transfer, capability matching, leases, heartbeats, and result verification. |

The engine/tool separation, typed schemas, central FFmpeg execution, guardrails, and structured errors remain correct. Existing public tools should compile into the new project/timeline/render substrate as product paths need them.

## 3. Five highest-leverage primitives

### 1. Durable project repository

```text
edit_project_create(
  name,
  width=1920,
  height=1080,
  fps={num: 30000, den: 1001},
  sample_rate=48000,
  storage_policy="managed"
)
→ {project_id, head_revision_id}

edit_project_get(
  project_id,
  revision_id="head",
  include=["timeline", "assets", "policies", "jobs"]
)
→ {project, revision, timeline, assets, policies}

edit_project_fork(
  project_id,
  revision_id,
  branch_name
)
→ {branch_id, head_revision_id}
```

Storage contract: canonical project metadata plus immutable revision snapshots; media lives in the artifact store.

### 2. Timeline IR plus atomic revision operations

```text
timeline_apply(
  project_id,
  base_revision_id,
  operations=[
    {op: "insert_clip", track_id, asset_id, at, source_in, source_out},
    {op: "move_clip", clip_id, at},
    {op: "set_property", node_id, path: "transform.scale", value: 1.1},
    {op: "add_effect", node_id, effect: {...}},
    {op: "split_clip", clip_id, at}
  ],
  message,
  validate_only=false
)
→ {revision_id, parent_revision_id, diff, validation}

timeline_diff(project_id, from_revision_id, to_revision_id)
→ {operations, affected_ranges, invalidated_render_nodes}

timeline_checkout(project_id, revision_id, branch="main")
→ {head_revision_id}
```

Time values must be rational or frame-based. Every timeline node must have a stable ID.

### 3. Persistent render jobs and worker scheduler

```text
render_submit(
  project_id,
  revision_id,
  target="proxy|preview|final",
  range={start, end}?,
  profile="agent-360p|review-720p|master",
  priority="interactive|batch",
  worker_pool="local",
  cache_policy="reuse"
)
→ {job_id, status:"queued"}

render_status(job_id, after_event_id?)
→ {
  status,
  stages,
  progress,
  worker,
  partial_artifacts,
  events,
  failure?
}

render_cancel(job_id)
render_resume(job_id)
```

Expose progressive outputs as MCP resources:

```text
kinocut://jobs/{job_id}/events
kinocut://jobs/{job_id}/preview.m3u8
kinocut://jobs/{job_id}/artifacts
```

Workers lease render-DAG nodes, fetch inputs by digest, publish verified artifacts, and remain replaceable.

### 4. Content-addressed asset, proxy, and artifact store

```text
media_ingest(
  project_id,
  uri,
  mode="copy|reference",
  fingerprint="sha256"
)
→ {asset_id, digest, metadata, analysis_status}

proxy_ensure(
  asset_id,
  profile="agent-360p",
  include=["video", "audio", "waveform", "scene_map"]
)
→ {job_id?, proxy_artifact_ids, cache_hit}

artifact_resolve(
  artifact_id,
  delivery="local_path|resource_uri|signed_url"
)
→ {artifact_id, digest, media_type, size, location, provenance}
```

Cache garbage collection must be reachability-based from project heads, pinned revisions, and retention policies.

### 5. Event-driven VLM review loop

```text
review_policy_set(
  project_id,
  triggers=["render.segment.ready", "render.completed"],
  reviewers=["technical", "vlm"],
  auto_patch="off|proposal|safe",
  max_iterations=3,
  required_gates=["technical", "editorial"]
)

review_run(
  project_id,
  revision_id,
  range?,
  objective,
  reviewers=["technical", "vlm"],
  comparison_revision_id?,
  auto_patch="proposal"
)
→ {review_id, findings, proposed_operations, gate_status}

review_decide(
  review_id,
  decision="accept|reject|accept_selected",
  finding_ids?,
  expected_revision_id
)
→ {revision_id?, rerender_job_id?}

event_poll(project_id, after_event_id, types?)
→ {events, next_event_id}
```

Each finding must contain:

```text
{severity, category, time_range, node_ids, evidence_artifact_ids,
 rationale, proposed_operations, confidence}
```

## Target architecture

```text
Existing compatibility tools (119 at audit time; 135 at release cutover)
          ↓ compile
Project + immutable Timeline IR + Revision DAG
          ↓ plan
Render DAG + policy/preflight validation
          ↓ execute
Local/remote job workers
          ↓ publish
Content-addressed artifacts + progressive proxies
          ↓ observe
Technical/VLM review events
          ↓ propose
Atomic timeline revision
```

This preserves the current differentiator—guardrails and proof—while moving it from individual file operations into the control plane of the entire editing lifecycle.

## Limits

The repository does not define deployment concurrency, remote-worker trust boundaries, artifact-retention budgets, or the allowed VLM providers. Those are implementation policy decisions; they do not change the architectural diagnosis.

Repository state remained clean. Epoch feedback was attempted, but the read-only sandbox prevented writing to `~/.epoch/`.
