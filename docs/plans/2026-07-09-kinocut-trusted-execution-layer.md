# Kinocut — The Trusted Execution Layer for Agentic Video

**status: APPROVED (Simon, 2026-07-10) - Phase 0 in progress. Repository/package rename merged under #53; publication, registry, site/TLS, and verification receipts remain before Phase 0 exit. Backlog filed: epic #85, issues #54-#84 + Track D #86-#94 + Track E #95-#107, gated `blocked:post-release` / milestone `kinocut-v2`.**
**Mode:** RALPLAN-DR consensus (DELIBERATE — high-risk, multi-phase architecture bet). Planner draft → Architect → Critic.
**Date:** 2026-07-09
**Author:** Planner (ralplan loop)
**Baseline:** `KyaniteLabs/kinocut`, with Forgejo as source of truth. **Current verified surface: 135 MCP tools + 114 CLI commands** (`tests/test_public_surface.py`, verified during the rename cutover). The planning snapshot was 124/103 before the rescue and post-rescue surfaces landed. The codebase now ships the `video_workflow_*` engine, which resumes within a single ordered job spec (see Phase 1 reconciliation).
**Thesis:** The most-talked-about crown in agentic video (~40 servers, no winner) goes to whoever ships the *trusted execution layer*: durable editing state, renders that watch themselves, one killer product motion. Kinocut's existing moat — guardrails + Video Receipts — is the seed of that trust layer.

> **HARD GATE STATUS:** The prerequisite `mcp-video` 1.6.0 release shipped and the repository/code rename in #53 merged. Phase 0 is therefore active, but not complete: Kinocut 1.7.0, the `mcp-video` compatibility shim, registry publication, site/TLS verification, and release receipts still must land. Every post-Phase-0 engineering issue remains `blocked:post-release` until Phase 0 exits. Labels are removed explicitly, phase by phase.

---

## RALPLAN-DR Summary

### Principles (guardrails on every decision)
1. **Kernel over tool #136.** The next architectural move is a durable substrate, not another synchronous verb. The existing 135-tool surface becomes compatibility adapters, never breaking removals.
2. **Trust is the product.** Every capability must answer "why would an agent-built video be resumed, reviewed, and shipped." Guardrails + Video Receipts are the differentiator; extend them, don't dilute them.
3. **Bounded loops with human gates — never autonomy theater.** Ship review loops that propose typed mutations; humans keep hook/thumbnail/final-review checkpoints. No silent auto-mutation of project head.
4. **Local-first, no meter, Apache 2.0.** No hosted-key dependencies that break offline use (the MiniMax-music lesson). Provider-agnostic adapters with local open-weights as first-class.
5. **Ship a moment at every phase exit.** Features don't get talked about; moments do. No multi-month "go dark" on the kernel.

### Decision Drivers (top 3)
1. **The identity gap is architectural, not featural.** Precisely (post-`video_workflow_*` release): there is **no durable PROJECT identity, no revisions / undo / branch, no cross-session edit state, and no async job submission** — the shipping workflow engine resumes only *within a single workflow spec* (spec-hash-pinned, per-step-hash cursor, synchronous sequential render). So agents can re-run a spec but cannot own, inspect, branch, or resume an *edit* across sessions. Without the kernel, everything else is polish on an RPC toolbox.
2. **A hot, monetizable, search-intent use case exists and the market is running toward our exact spot.** "Turn my podcast into TikToks" has buyers; "call FFmpeg over MCP" does not. r/selfhosted asks verbatim for "a local Opus Clip." We are the only guardrailed, local, no-meter native there.
3. **Two hard external clocks.** MCP Tasks primitive (SEP-1686) is on the official 2026 roadmap — build async render idiomatic to it now. EU AI Act Art. 50 synthetic-content labeling becomes enforceable **Aug 2026** and no video MCP ships C2PA today — first-mover compliance + press window is ~3 weeks out.

### Viable Options (sequencing)

**Option A — Kernel-first (pure).** Build all five primitives to depth before product/verbs.
- Pro: correct dependency order; watching guardrail + verbs + review surface all sit on the substrate; no rework.
- Con: longest time-to-visible-value; largest refactor blast radius held open for months; violates Principle 5 (no moment); highest risk of the "go dark" trap the synthesis explicitly warns against.

**Option B — Verbs/product-first (pure).** Ship the ~10 intent verbs + one-command repurposing on top of today's 135-tool surface; defer the kernel.
- Pro: fastest distribution moment (Remotion-style skill install); immediately cuts the agent-tax; product is the demo.
- Con: builds the *identity* (trust layer) on sand — no durable state, no undo, no review loop; an undifferentiated Opus Clip clone that funded incumbents match; contradicts Driver 1 and Principle 2.

**Option C — Kernel thin-slice driven by the repurposing product (tracer bullet). [CHOSEN]** Build the five primitives at MVP depth, forced through ONE real vertical (long-form→short-form), then thicken; verbs ride on top; watching guardrail layers once the event plane + render jobs exist.
- Pro: honors dependency order AND ships a moment each phase; product is the forcing function that keeps the kernel honest and demoable; smallest safe increment of a large refactor; existing tools stay green throughout.
- Con: requires disciplined scope-holding (thin slice must resist becoming pure Option A); the product path constrains which kernel corners get built first (acceptable — it builds the corners that matter).

**Invalidation rationale.** Option A rejected: no distribution moment for months is the documented failure mode for solo-maintainer OSS and directly violates Principle 5. Option B rejected: it forfeits the only defensible identity (Driver 1) and lands us in the funded-competitor knife-fight the synthesis names as a trap. Option C is A's correctness with B's momentum, gated by the product so the kernel is never speculative.

---

## Phase Plan

Legend: **Entry** = must be true to start · **Exit** = done-definition + gate to next phase · file anchors are repo-relative to the Kinocut repository root.

### Phase 0 — Kinocut rename cutover (identity pivot)
Not new architecture; the identity pivot that precedes every distribution moment. Tracked in Forgejo `KyaniteLabs/kinocut#53`.

**Entry:** Met. `mcp-video` 1.6.0 is published and the Kinocut namespaces are secured.
**Work breakdown (issue-sized):**
- P0.1 GitHub/Forgejo repo rename → Kinocut (auto-redirects); update remotes/CI badges.
- P0.2 Publish real `kinocut` PyPI + npm packages; configure npm trusted publisher (OIDC `publish.yml`, disallow tokens, auto-provenance); delete one-time tokens.
- P0.3 Publish `mcp-video` PyPI shim depending on `kinocut`; defend npm `mcp-video` namespace confusion story.
- P0.4 Update `server.json` (root) + MCP registry entry (`io.github.KyaniteLabs/...`); CLI command `mcp-video` → `kino` with alias.
- P0.5 Docs/site sweep: README, `llms.txt`, GitHub Pages (kill stale "81 tools, FFmpeg + Remotion"), `docs/`, CHANGELOG, `index.html`.
**Exit:** `kino` CLI works from a clean `pip install kinocut`; GitHub renamed; registry entry live; site/docs say Kinocut + correct tool count; `mcp-video` shim resolves.
**Distribution moment:** "mcp-video is now Kinocut — here's the 2.0 vision" launch post.

### Phase 1 — Minimal kernel corners, shipped INSIDE the first repurposing moment
Only the corners Phase 2 actually invokes: **durable edit project + async render/resume + receipt lineage**. New modules under `kinocut/kernel/` so the existing engine/tool layer is untouched and stays green. Async render is shaped to MCP Tasks (SEP-1686) from day one, poll-first. **Phase 1 does not release independently — its exit IS the Phase 2 repurposing moment (merged exit); the first kernel code reaches the public inside the "made just by prompting" demo.** No moment-less phase exists in this plan.

**Explicitly DEFERRED to Phase 3** (where the review loop is their first real consumer, so Phase 1's scope-claim is literally true): revision-DAG branching / `fork` / `checkout` / `diff`; the full **Timeline-IR graph** (stable node IDs, rational timebase, nested sequences, effect stacks) and its render DAG; the **multi-event typed plane**. Phase 1 revisions are **append-only linear** (monotonic counter, no branch/undo) — enough for resumability + receipt lineage, nothing more claimed.

**Entry:** Phase 0 exit; `kinocut-v2` milestone opened; P1 issues un-blocked (label removed) by explicit human act.

**P1.0 — ADR-0008 + CONTEXT.md (do FIRST, before any kernel code).** (`0007` is taken by the shipped agent-workflow-engine ADR — the kernel ADR is **`docs/adr/0008-editing-kernel.md`**.) Name the kernel nouns; disambiguate the THREE existing "project" meanings — cinematic **creation project** (`creation_engine.py`), **hyperframes project** (`hyperframes_engine.py`), new durable **edit project** (kernel unit; API noun `edit_project_*`). Rename "worker" (on CONTEXT.md's avoid-list) → **"render runner"** (the render-executing process). **CONTEXT.md's avoid-list entry for "project" (under Timeline) is being deliberately AMENDED here, not violated** — the amendment records the three disambiguated senses so future readers see an intentional decision, not drift. Restate the domain invariant as **Tool → (Engine | kernel-compile)**: a tool either delegates 1:1 to an engine function (legacy path) or compiles into the kernel (new path). Also settle the workflow-engine relationship (below) in this ADR. Update `CONTEXT.md`.

**Relationship to the shipping `video_workflow_*` engine (settle in P1.0; answers the executor's "which resume mechanism do I build?").** The 1.6.0 release ships `video_workflow_plan / validate / render / inspect` over an ordered, backward-reference-only JSON job-spec, WITH a spec-hash-pinned resume cursor (per-step input/output sha256 + re-hash-on-resume, skip-completed / re-run-from-first-failing) and a workflow-receipt (`receipt_kind: "workflow"`) carrying per-step hashes + a cleanup manifest. **The kernel WRAPS this engine; it does not rebuild or supersede it.** Concretely:
- **P1.2 `render_submit/status/cancel/resume` WRAPS `video_workflow_render`**: it adds (a) async submission over a detached render runner (workflow render is synchronous/sequential today), (b) durable edit-project identity as the unit of work, and (c) job-store persistence — but it **reuses the existing workflow resume cursor** (spec-hash + per-step-hash) rather than inventing a second resume mechanism. The executor builds ON the shipped resume, not a parallel one.
- **P1.4 receipt lineage EXTENDS the workflow-receipt schema** (`receipt_kind: "workflow"`) — adding `edit_project_id / revision_id / job_id` and preserving the existing per-step hashes + cleanup manifest — rather than only extending the legacy Video Receipt. The `receipt_kind` discriminator (already in the codebase, `video_workflow_inspect` is legacy-tolerant) lets the kernel evolve the workflow receipt without breaking inspectors.
- **Net effect: Phase 1 shrinks** toward "**wrap the workflow engine + make it async + add durable project identity + extend the workflow receipt with lineage**." Confirm the exact wrap surface during P1.0 before opening P1.2/P1.4 issues.

**Durable-job lifecycle — settled BEFORE building P1.2.** The server runs over **stdio**, so process lifetime is tied to the client. **Chosen: persistent on-disk job store + detached render-runner subprocess, reconciled on startup.** `render_submit` forks a detached subprocess (survives client/stdio-server exit); job state (queued/running/failed/done, stage, partial artifacts) persists to the job store; on next server start, scan the store and reconcile — reattach live PIDs, resume interrupted jobs from the last completed stage, mark orphans failed. *Rejected:* in-process threads (die with the stdio server → no resume) and a standalone daemon (ops burden, breaks local-first simplicity). **`event_poll` / `render_status` are poll-first; nothing critical depends on server-initiated notifications.** Each primitive (project store, job store, render runner, CAS) gets **SEPARATE Epoch sizing** before its issue opens.

**Work breakdown (issue-sized; Codex API sketches are the contract — `scratchpad/out-codex.md` §3):**
- P1.1 **Durable edit-project repository** — `edit_project_create/get` (NO `fork` yet — Phase 3). Canonical project metadata + append-only linear revision snapshots on disk; stable project/asset/artifact IDs. New: `kinocut/kernel/project.py`, managed project dir.
- P1.2 **Persistent async render jobs + render runner (wraps `video_workflow_render`)** — `render_submit/status/cancel/resume`, `job_id`, stage progress, partial-range, progressive artifacts; on-disk job store + detached runner + startup reconcile (per lifecycle decision). Renders a **linear operation list** from the current revision (NOT a render DAG — that arrives with the Timeline IR in Phase 3), executed via the existing workflow engine underneath. New resources under `kinocut://jobs/{id}/events|preview.m3u8|artifacts` (URI decision below). New: `kinocut/kernel/render_jobs.py`, `kernel/runner.py`, `server_resources.py`.
  - **Coexistence with synchronous `video_workflow_render`:** both remain callable. `render_submit` is the **poll-first async** path (returns `job_id`, survives disconnect, resumes across sessions) and is what durable/long-form edits use; the synchronous `video_workflow_render` stays for direct one-shot / short jobs and legacy callers. **Intent verbs (P2.5) route the durable/long-form product path to `render_submit`; the sync tool is not deprecated** — `render_submit` wraps it internally, so this is a wrap, not a hard migration. No behavior change to existing `video_workflow_*` callers.
- P1.3 **Content-addressed store** — `media_ingest`, `proxy_ensure`, `artifact_resolve`. Digest-keyed assets/proxies/transcripts/scene-maps/renders; cache identity = source digest + normalized op params + toolchain version + output profile; reachability GC from project heads. New: `kinocut/kernel/cas.py` (supersedes the in-memory ffprobe cache role of `kinocut/engine_probe.py:16` for kernel paths).
- P1.4 **Receipt lineage** — extend the Video Receipt so every artifact carries `{edit_project_id, revision_id, job_id, source_digests, output_digest, toolchain_fingerprint}`. This is the trust payload the moment depends on. Extends the receipt writer + `docs/VIDEO_RECEIPT.md`.
- P1.5 **Minimal event poll** — `event_poll(project_id, after_event_id, types?)` for exactly the events Phase 2 needs: `revision.created`, `render.completed`, `quality.gate.failed`. (Full typed plane → Phase 3.) New: `kinocut/kernel/events.py`.
- P1.6 **Compat bridge (repurposing slice only)** — thin adapter so the **timeline-mutating** repurposing-path tools (trim, merge, subtitle burn-in, reframe/crop, silence-removal cuts) compile into an edit project/revision instead of path-in/path-out; these align with the shipped workflow op allowlist (`trim|resize|merge|add_text`) where possible. **Note (Architect advisory):** transcribe, highlight-detect, and scene-detect are **CAS artifact producers, not timeline mutations** — they populate the content-addressed store (P1.3) that selection/reframe consume, and are therefore NOT in the P1.6 bridge set. Fate of the other tools decided in Cross-cutting decisions. New: `kinocut/kernel/compat.py`.

**Acceptance (kernel corners):** create edit project → ingest media (CAS; `cache_hit` on repeat) → apply the repurposing operation list → `render_submit` returns a `job_id` immediately → `render_status` shows stage progress → **kill the server mid-render, relaunch, job resumes from the last completed stage** → final artifact carries full receipt lineage → a poller sees `render.completed`. Existing tools + all prior tests pass unchanged; existing `video_workflow_*` callers see no behavior change.
**Exit = Phase 2 exit (merged).** No independent Phase 1 release.

### Cross-cutting decisions (settled here, referenced above)

**Fate of the un-bridged tools.** Only the timeline-mutating repurposing-path subset (P1.6: trim, merge, subtitle burn-in, reframe/crop, silence-removal cuts) compiles into the kernel. **The remaining bulk of the 135-tool surface stays legacy path-in/path-out compatibility adapters *indefinitely*** — there is NO plan or phase to bridge all of them. They keep working unchanged; individual tools graduate into the kernel only on demand when a product path needs them. "135 tools" is a **depth claim**, not a migration backlog. This bounds the refactor and honors "never breaking removals."

**Resource URI scheme.** All new kernel resources are minted as **`kinocut://`** from Phase 1 (they are brand-new surfaces introduced post-rename, so there is no wire consumer to break). Any pre-existing `mcp-video://` resource keeps an alias through one deprecation window. *Schema-regression risk:* existing consumers of any current `mcp-video://` resource — mitigated by the alias + a `call_tool`/resource round-trip regression test (see Test Strategy). Rejected: keeping `mcp-video://` on the wire post-rename (perpetuates the retired brand on the most durable surface).

### Phase 2 — Repurposing as THE product + intent-verb surface
The one killer motion on the kernel. This is the flip: "no generation" becomes stated scope; the pipeline's output is the viral artifact. **Phases 1 and 2 ship as ONE public moment** — the kernel corners (Phase 1) go live carrying this product; there is no separate Phase 1 release.

**Entry:** Phase 1 corners built (durable project + async render/resume + receipt lineage green in CI).
**Work breakdown:**
- P2.1 **One-command long-form→short-form** — `repurpose` verb: ingest → transcribe → highlight-detect → 9:16 reframe → captions → receipt, all through the kernel (durable project, async render, receipt). Extends `engine_repurpose.py` + `server_tools_repurpose.py`.
- P2.2 **Steerable/trainable moment selection** (demand JTBD #1) — expose selection criteria (keywords, speaker, energy, retention heuristic) as parameters; "train on MY content" via example clips. New selection module under `kinocut/kernel/` or `kinocut/ai_engine/`.
- P2.3 **Speaker-aware 9:16 reframe** (JTBD #2, OpusClip's moat feature) — subject-tracking auto-reframe; build on existing crop/scene-detect engines.
- P2.4 **Reliable word-timed styled captions** (JTBD #3 — reliability *is* the differentiator; avoid the Captions.ai desync bug) — word-level timing from Whisper, styled burn-in; harden `engine_subtitles.py` / `engine_subtitle_generate.py` (note prior BUG-1 force_style class).
- P2.5 **Intent-verb surface** — ~8–12 semantic verbs (`remove_silence`, `reformat_vertical(subject_tracking=auto)`, `cut_to_beats`, `inject_broll`, `repurpose`, …) + a `video_intent` router; demote the 135-tool surface to internals/compat. "135 tools" becomes a depth claim. Durable/long-form verbs route to async `render_submit` (P1.2); the sync `video_workflow_render` stays for direct short jobs. New: `kinocut/server_tools_intent.py`.
- P2.6 **Local semantic footage search** (frontier lane: NL moment retrieval = 12-month table stake) — "find the moment where X happens" over local files via a VLM/embedding index. **Built as its own kernel capability** (index stored as digest-keyed artifacts in the CAS from P1.4, GC'd with the project) that the repurposing bet *consumes* to make steerable moment selection (P2.2) real. Rationale for its-own-capability over folding into repurpose: the index is reusable by review (P3), b-roll (P2.8), and future search verbs; repurpose is one consumer. New: `kinocut/kernel/semantic_index.py` + a `find_moments` verb.
- P2.7 **Filler-word + restart-phrase removal** (demand JTBD #6) — beyond current silence removal: Silero VAD + Whisper word timestamps to cut "um/uh" and false-start restarts. Natural extension of `video_ai_remove_silence` (`ai_engine/`); competitor timkulbaev/ai-video-editor already ships this. Emits typed cut ops through the kernel (reviewable, not silent).
- P2.8 **Auto b-roll suggestions** (demand JTBD #9; agy's top wedge "Magic B-Roll") — transcript-keyed proposals surfaced as **human-reviewable proposed mutations, never silent inserts**. Backs the `inject_broll` verb; proposal shape reuses the review-loop finding format from P3.5, so this lands as *proposals in Phase 2, gated acceptance once the review loop is live in Phase 3*. **(Architect advisory):** in Phase 2 these proposals anchor to **`time_range` only** — stable `node_id` anchoring is not available until the Timeline IR lands in P3.0, so the Phase-2 proposal format carries time ranges and upgrades to time-range + node-id in Phase 3.
- P2.9 **Caption translation, ES-first + honest per-surface language coverage** (demand JTBD #7 — only 2 of 9 incumbents deliver 30+ languages honestly; bilingual EN/ES is the maintainer's brand) — ship caption translation now; codify a **feature principle that each surface states its real coverage** (transcribe vs translate vs dub are different guarantees, never conflated). Local TTS *dubbing* is deferred to Phase 4 (P4.4). Extends `engine_subtitle_generate.py` + docs.
- P2.10 **Editing-skill archiving** (FireRed-OpenStoryline's standout feature, 3k★) — save a proven edit workflow (a project's revision path + verb sequence) as a reusable, shareable skill/recipe. Pairs with the intent-verb surface (P2.5) and golden workflows; recipes live in `skills/`.

**Acceptance (bet #3 — repurposing; falsifiable thresholds on the golden fixture, tune during build):**
- **One-command:** a single `repurpose` call turns the fixture podcast/long-form into N short-form clips, each with a workflow receipt carrying lineage (P1.4).
- **Steerable selection is deterministic:** same input + same params → **identical selection set** (same clip count + same in/out timecodes, byte-stable selection JSON). Rendered output is compared by **SSIM ≥ 0.98** against the golden render, NOT byte-equality (honors the shipped honest-determinism note: no byte-identical renders across FFmpeg builds).
- **Speaker-aware reframe:** the detected face centroid stays inside the 9:16 safe-area for **≥ 95% of clip duration** on the fixture (measured frame-sampled).
- **Caption reliability:** every burned word's on-screen start is within **≤ 80 ms** of the Whisper word-timestamp ground truth on the fixture; **zero** desync drift accumulation over a 60 s clip.
- **Gates:** transcript-confidence gate, first-15-seconds retention check, and idempotent publishing all enforced; humans retained only at hook/thumbnail/final-review.
**Exit:** golden workflow `06-repurpose-package` runs end-to-end on the kernel and produces a receipt; intent surface is the default exposed surface; the full tool surface reachable as internals.
**Distribution moment:** package repurposing as an **agent skill with one-line install** (`skills/` already exists); post one genuinely good output tagged "made just by prompting" (the Remotion mechanic).

### Phase 3 — The watching guardrail (renders that review themselves)
Evolve guardrails from static preflight to a **closed review loop**. Converts the one defensible moat into the category-defining feature. Runs on Phase 1's event plane + render jobs.

**Entry:** Phase 1 async render + minimal event poll live; Phase 2 producing artifacts to review.
**Kernel deepening (prerequisite — the review loop is the first real consumer of these):**
- P3.0 **Promote the kernel to graph depth.** Land the pieces deferred from Phase 1 now that a consumer needs them: the full **Timeline IR** (stable node IDs, rational timebase, effect stacks, nested sequences) compiling to a **render DAG** (replaces the linear op-list render from P1.2 and the one-shot DTO role of `kinocut/models.py:310` / `kinocut/engine_timeline.py` for kernel paths); the **revision DAG** — `edit_project_fork`, `timeline_apply/diff/checkout`, branch/undo/compare-and-swap against `base_revision_id`; and the **full typed event plane** (`render.node.completed`, `render.segment.ready`, `review.*`). Findings can only anchor to `node_ids` once the IR exists, so this precedes P3.1. New: `kinocut/kernel/timeline_ir.py`, `revision.py`; extend `events.py`, `render_jobs.py`.
**Work breakdown (Codex primitive #5):**
- P3.1 **Review API** — `review_policy_set`, `review_run`, `review_decide`, plus review events (`review.finding.created`, `review.patch.proposed/accepted`). New: `kinocut/kernel/review.py`.
- P3.2 **Metric QC third (already owned)** — VMAF, LUFS, black frames, A/V sync via `engine_compare_quality.py` / quality guardrails, anchored to time ranges.
- P3.3 **Vision QC third** — VLM rubric on sampled keyframes ("caption legible? overlapping a face?"); provider-agnostic, local-capable; consumes proxies from CAS.
- P3.4 **Narrative QC third** — retention heuristics incl. first-15-seconds check (the demand lane found practitioners hand-check exactly this). Scoped honestly: "rank/flag" fidelity, not "this cut at 00:12 loses viewers" (open research gap — do not overclaim).
- P3.5 **Findings → typed mutations** — every finding carries `{severity, category, time_range, node_ids, evidence_artifact_ids, rationale, proposed_operations, confidence}`; bounded iteration (`max_iterations`, `required_gates`); **never** silent mutation of project head.

**Acceptance (bet #2 — watching guardrail):** `review_run` on a revision returns findings anchored to time ranges + timeline node IDs, each with a proposed typed mutation. **Metric QC (VMAF / LUFS / black frames / A-V sync) is the guaranteed floor and runs fully OFFLINE — the trust story NEVER hard-depends on a hosted key (the MiniMax-music lesson).** Vision (VLM) and narrative QC are **graceful enhancements that degrade to absent**: with no model/key available, `review_run` still returns a valid metric-only verdict and gate status, never an error. Iteration is bounded and gated; a rejected finding never alters head; `review_decide(accept)` produces a new revision + rerender job. Grades the *edit*, not just the finished file.
**Exit:** review loop passes on golden workflows; Video Receipt now includes `review_artifacts` + gate outcomes.
**Distribution moments:** the **self-edited launch video** ("cut by the agent using Kinocut; manifest attached" — unclaimed format, simultaneously the demo of bets #1–3); publish the **Video-Editing Agent Bench** (the Aider mechanic — every model release becomes free press).

### Phase 4 — Force multipliers + interchange
Own the last mile and the edges, once the review loop is live. (C2PA provenance signing is NOT here — it runs on the kernel-independent **Parallel Track P** from Phase 0; see the Distribution calendar. By the time Phase 4 lands, C2PA already ships on final exports.)

**Entry:** Phase 3 review loop live.
**Work breakdown:**
- P4.1 **Generative last-mile adapter** — provider-agnostic `generate` (cloud APIs + local Wan 2.2 / LTX-2 / HunyuanVideo on 24GB GPU); own fps/color normalization, upscale, audio replacement, loudness, stitching. Guardrails: **spend caps before the API call**, prompt logging for reproducibility. Don't generate — *finish*.
- P4.2 **OTIO in/out** — OpenTimelineIO import/export (the agent-legible EDL; interchange into DaVinci/Premiere/FCP). "Cheap to claim, unclaimed." New: `kinocut/kernel/otio_io.py`.
- P4.3 **Human review surface** — hot-reloading timeline/preview page (Hyperframes can render it) so "agent proposes, human approves" is real for non-technical humans.
- P4.4 **Local TTS dubbing, ES-first** (demand JTBD #7 tail) — local text-to-speech dubbing over the translated captions from P2.9; kept honest under the per-surface coverage principle (dub ≠ translate ≠ transcribe). Local-first providers only; flows through the finishing + loudness path.

**Exit:** generated clips flow through the finishing + guardrail path; OTIO round-trips into an NLE; review page shows a live project. (C2PA already live via Track P.)
**Distribution moments:** OTIO-into-DaVinci demo; grind the lists (vidocu, ffpipe, Docker MCP Catalog, Claude Connectors verified tier, awesome-mcp); n8n template + one faceless-automation YouTube tutorial; Guardrails-as-story backed by Bloomberry's 1,412-server data.

---

## Distribution calendar & Parallel Tracks

**Parallel Track P — kernel-independent, starts at Phase 0, runs alongside everything.** These harvest time-boxed wins and de-risk "solo-maintainer-never-finishes"; neither waits on the kernel.
- **PT.1 — C2PA provenance signing** on final render output (works on the existing path-based export path). First video MCP to ship C2PA; compliance (EU AI Act Art. 50, enforceable Aug 2026) + press story. Ship as early as possible to catch the ~3-week window; it does not block on and is not blocked by any kernel phase.
- **PT.2 — Repurposing-on-current-tools skill + "made just by prompting" moment.** A path-based v1 of the repurpose demo, packaged as a one-line-install agent skill, shipped BEFORE the kernel lands to seed the narrative and prove momentum. **Superseded at the Phase 1–2 exit** by the kernel-backed version (upgraded: now with receipt lineage + resumability). PT.2 is explicitly a marketing seed, NOT the durable identity (see Pre-Mortem #2).

**Main-track moments (tied to phase exits):**
| When | Moment |
|---|---|
| Phase 0 exit | "mcp-video is now Kinocut — the 2.0 vision" rename launch |
| Track P (ASAP) | C2PA-first press (PT.1); current-tools repurposing skill (PT.2) |
| Phase 1–2 exit (merged) | Kernel-backed repurposing "made just by prompting" — supersedes PT.2, now trust-backed |
| Phase 3 exit | Self-edited launch video + Video Receipt; publish the Video-Editing Agent Bench |
| Phase 4 exit | OTIO-into-DaVinci; roundup/list submissions; n8n template + faceless-automation tutorial; Guardrails-as-story |
| Ongoing | npm `mcp-video` namespace defense; Bloomberry thin-wrapper contrast |

---

## Test Strategy

**Doctrine (from prior remediation lesson):** mocked tests structurally miss filtergraph bugs — TDD against **real FFmpeg on synthetic lavfi fixtures**, not private `~/Downloads` media. Keep authoring and verification in separate passes; never self-approve.

- **Unit** — Timeline IR ops (insert/move/split/set_property), revision DAG (parent/branch/checkout/diff), CAS cache-key determinism + reachability GC, event ordering, intent-router dispatch, caption word-timing.
- **Integration** — render job lifecycle (submit→progress→partial→complete→cancel→resume), event plane delivery, compat bridge (old tool → project/revision), review loop (findings→proposed ops→decide→rerender), C2PA manifest verification.
- **E2E** — full `repurpose` pipeline on a real podcast fixture produces N clips + a valid Video Receipt + passes all gates; Video-Editing Agent Bench tasks complete through the MCP surface.
- **MCP wire** — `call_tool` round-trip (not just `list_tools`) for the intent verbs + kernel tools; schema-regression guard.
- **Observability** — structured logging on jobs/events; Video Receipt as the audit trail (user_intent, tool_calls, edits, guardrails_triggered, quality scores, review_artifacts, pending review).
- **CI gates** — full suite green on push (Forgejo + GitHub); bare-install lane (the class that broke 1.4.1); coverage floor on new kernel modules; keep the full existing suite passing every phase.
- **Public-surface drift (known per-phase step)** — `tests/test_public_surface.py` asserts **exact** MCP tool + CLI command counts and boots a real stdio server. Every kernel tool added in Phases 1–3 (`edit_project_*`, `render_submit/status/cancel/resume`, `media_ingest`, `proxy_ensure`, `artifact_resolve`, `event_poll`, `find_moments`, `review_*`, intent verbs, …) **trips this drift test by design**. Treat updating the drift manifest (tool/CLI counts + names) as a **required, deliberate step in every phase that adds a tool** — not a surprise failure. Also add a `call_tool` / resource round-trip test for each new kernel tool + the `kinocut://` resources (schema-regression guard).

## Risk Register (top 5)

| # | Risk | Likelihood/Impact | Mitigation |
|---|------|-------------------|------------|
| 1 | Kernel refactor destabilizes the existing suite or breaks the 135-tool surface / `video_workflow_*` engine | Med / High | Kernel is **additive** (`kinocut/kernel/`), existing engine untouched; kernel WRAPS `video_workflow_render` (no rebuild); tools = compat adapters, never removals; TDD real-FFmpeg; green-suite gate at every phase exit. |
| 2 | Scope explosion — kernel becomes a multi-month sink with no shippable moment (the "go dark" trap) | Med / High | Option C thin-slice forced through the repurposing product; each phase exits with a distribution moment; Phase 1 builds only the corners Phase 2 needs. |
| 3 | C2PA / EU AI Act Aug-2026 window missed | High / Med | **Parallel Track P (PT.1)** — provenance signing on the existing path-based export is fully kernel-independent, starts at Phase 0, blocks on nothing; ship ASAP even if press lands near the date. |
| 4 | Factory ~30-min auto-triage starts post-Phase-0 work before publication/registry/site receipts land | Med / High | Keep `blocked:post-release` + `kinocut-v2` on every post-Phase-0 issue; unblocking is an explicit per-phase act only after the Phase 0 exit receipt. |
| 5 | Solo-maintainer bandwidth + agent-fleet coordination (worktree base-drift, false-green delegated PRs) | Med / Med | Pinned worktree bases + `merge-base --is-ancestor` verify before accepting any delegated PR; verifier pass separate from author; one-artifact-one-commit; env-scrub on headless delegations. |

*Watched (not top-5):* VLM review reliability / retention-prediction over-claim → scope narrative QC to "flag/rank" fidelity and keep human gates (Principle 3).

## Out of Scope (the trap list)
- **Tool #136** — adding features instead of building the kernel (the meta-trap).
- **Full-autonomy theater** — single-click no-human editing; ship bounded loops with human gates only.
- **Competing head-on with generators** — solo maintainer vs. funded giants; be the last mile / finisher, not the model.
- **Kimi's trap list** — emotion-adaptive editing, NFT provenance, avatar farms, spatial-video-first.
- **Hosted-key dependencies that break local-first** (the MiniMax-music lesson) — keep offline-capable.
- **Cloud SaaS / credit-metering business model** — no meter; the market resents credit-math.
- **Unchanged existing out-of-scope** — GPU acceleration, RTMP/HLS streaming as a domain.

*Deferred (explicitly, with rationale — revisit post-kernel):*
- **Multicam sync + A/B-roll classification** — Eddie AI territory, heavy; not a solo-maintainer fit yet.
- **Per-viewer dynamic renders** (Kimi's "compiled variants") — needs the kernel + render DAG mature first; premature before Phase 1 lands.
- **Live-stream kernel** — the repo's stated out-of-scope (streaming is a different domain); unchanged.
- **Eye-contact correction / generative jump-cut smoothing** — funded-incumbent ML; a trap for a solo maintainer (be the finisher, not the model).

---

## ADR — Kinocut becomes the trusted execution layer via a product-driven kernel

- **Decision:** Adopt Option C. Build **only the kernel corners the repurposing product invokes** (durable edit project + async render/resume + receipt lineage) at MVP depth, shipped INSIDE the repurposing moment (Phases 1–2 merged); defer the Timeline-IR graph + revision DAG + full event plane to Phase 3 where the review loop consumes them; then force multipliers. Keep the timeline-mutating repurposing-path tools bridged and the rest of the 135-tool surface as legacy compat adapters indefinitely. The kernel **wraps** the shipped `video_workflow_*` engine (reuses its resume cursor + extends its `receipt_kind:"workflow"` schema), not rebuilds it.
- **Drivers:** (1) the identity gap is architectural (path-as-identity, one-shot DTO, sync-only, state-deleted); (2) a hot monetizable use case sits exactly where the market is heading; (3) two external clocks — MCP Tasks SEP-1686 (build idiomatic now) and EU AI Act Aug-2026 C2PA (first-mover window, chased on Parallel Track P).
- **Alternatives considered:**
  - **Option A — kernel-first-pure.** Rejected: no moment for months = the go-dark trap; largest refactor blast radius held open with nothing shipping.
  - **Option B — verbs/product-first-pure.** Rejected *as the primary sequence*: building the trust identity on path-based tools with no durable/reviewable state yields an undifferentiated clone in a funded-competitor knife-fight. **Steelman (Architect):** disciplined-B is right that a moment must ship NOW, on existing tools, before the kernel is done — waiting on the kernel is the real solo-maintainer risk, and the Aug-2026 C2PA window won't wait. **Adopted from B:** the kernel-independent **Parallel Track P** (C2PA signing + a current-tools repurposing skill/moment from Phase 0) absorbs B's best idea into C — we harvest an early moment and the compliance window without betting the durable identity on the un-durable path. C keeps the kernel as the identity; B's momentum rides *alongside* it (Track P), not *instead* of it.
- **Why chosen:** Option C is A's correctness with B's momentum; the product keeps the kernel honest and demoable; smallest safe increment of a large refactor with the existing suite green throughout; the merged Phase 1–2 exit guarantees the first kernel code ships inside a real moment.
- **Consequences:** Positive — durable/reviewable/resumable edits become the category-defining identity; guardrails moat extends into a control plane; a distribution moment at every exit AND two early kernel-independent moments on Track P. Negative/cost — requires disciplined scope-holding on the corners (P3.0 carries real deferred weight); the product path dictates kernel build order; a linear-then-DAG two-step for the timeline (Phase 1 op-list → Phase 3 render DAG) means one deliberate re-work seam at P3.0.
- **Follow-ups:** finish the Phase 0 publication/registry/site receipt; write ADR-0008 (`docs/adr/0008-editing-kernel.md`) + CONTEXT.md noun disambiguation/amendment (P1.0) before any kernel code, including the `video_workflow_*` wrap decision; re-run Epoch sizing before each implementation issue opens; confirm the durable-job lifecycle (detached-subprocess-reconciled-on-startup) survives a real stdio relaunch test; decide allowed VLM providers + artifact-retention budget + remote-worker trust boundary.

---

## Pre-Mortem (3 failure scenarios)
1. **"We shipped a kernel nobody could see."** Six weeks in, the kernel is half-built, no product runs on it, no moment shipped, momentum dies. → *Prevention:* Phases 1–2 have a **merged exit** — the kernel corners cannot "finish" without the repurposing product they carry; if the slice can't demo, the phase isn't done. Track P (PT.2) also ships an early current-tools moment so momentum never depends on the kernel finishing.
2. **"The marketing seed became the identity."** The current-tools repurposing skill (PT.2) hits a moment fast, and we let that path-based version stand in as the durable product — no receipt lineage, no resumability, no review — so we end up an undifferentiated clone with an unbacked trust story. → *Prevention:* PT.2 is explicitly labeled a marketing seed, **superseded at the Phase 1–2 exit** by the kernel-backed version; the durable product (P2.1) MUST route through the kernel (edit project / revision / receipt lineage); reject any durable-path repurpose that bypasses it.
3. **"The VLM loop lied and shipped a bad cut."** The watching guardrail auto-accepts a low-confidence finding, mutates head, and the self-edited launch video has a caption over a face. → *Prevention:* never silent-mutate head; bounded iteration + required gates + human final-review; narrative QC scoped to flag/rank; the launch video itself carries a Video Receipt proving the gates ran.

## Open Questions (persist to `.omc/plans/open-questions.md`)
- Phase 0 publication completion - Kinocut 1.7.0, the `mcp-video` 1.6.1 shim, registry, site/TLS, and receipts must all verify before post-Phase-0 labels are removed.
- ADR-0008 (P1.0): confirm the `edit_project` API noun vs a user-facing "Cut" alias for the durable-project noun. (naming, before code)
- Exact post-release counts at cutover (P0.5): **resolved at 135 MCP tools + 114 CLI commands**, enforced by `tests/test_public_surface.py`.
- `video_workflow_*` wrap surface (P1.0): confirm `render_submit` reuses the workflow spec-hash/per-step-hash resume cursor rather than adding a second mechanism, and that P1.4 extends the `receipt_kind:"workflow"` schema.
- Per-primitive Epoch sizing (project store / job store / render runner / CAS) — pending before each Phase 1 issue opens.
- Durable-job lifecycle: validate detached-subprocess-reconciled-on-startup survives a real stdio relaunch on macOS + Linux before committing P1.2.
- Allowed VLM providers + local-capable rubric model for Phase 3. (affects local-first claim; metric-QC floor is unaffected)
- Artifact-retention budget + GC policy defaults for CAS. (affects disk footprint)
- Remote render-runner trust boundary — local-only through Phase 3; revisit before any distributed runner.
- C2PA (PT.1) signing library choice + whether to run a dedicated Phase-0 sprint to catch the Aug-2026 window.

---

## Revision History
- **Rev 1 (2026-07-09, Planner):** initial RALPLAN-DR draft — 5 principles, 3 drivers, Options A/B/C (C chosen), Phases 0–4, Tier-1 acceptance, risk register, distribution moments, out-of-scope, ADR, pre-mortem. Scope addendum folded in (semantic search, filler removal, b-roll, translation ES-first, skill archiving; 4 deferred items).
- **Rev 2 (2026-07-09, Planner — post-Architect SOUND-WITH-CHANGES):** incorporated all 7 required changes.
  1. **Re-scoped Phase 1** to only the corners Phase 2 invokes (durable edit project + async render/resume + receipt lineage); deferred revision-DAG branching/fork/checkout/diff, the full Timeline-IR graph, and the multi-event plane to **Phase 3 (P3.0)** where the review loop consumes them. Phase 1 revisions now append-only linear.
  2. **Killed the moment-less phase** — merged Phase 1↔2 exits; first kernel code ships inside the repurposing moment; Phase 1 no longer releases independently.
  3. **Added P1.0** — ADR-0007 + CONTEXT.md: named kernel nouns, disambiguated the three "project" meanings, renamed "worker" → "render runner", restated invariant Tool → (Engine | kernel-compile).
  4. **Specified the durable-job lifecycle** — persistent on-disk job store + detached render-runner reconciled on startup (alternatives rejected with reasons); poll-first; per-primitive Epoch sizing flagged.
  5. **Metric-QC floor** made explicit in Phase 3 acceptance — offline-guaranteed, VLM/narrative degrade to absent, never a hosted-key hard-dependency.
  6. **Added Cross-cutting decisions** — ~113 tools stay legacy path-in/path-out indefinitely (no bridge-all phase); new kernel resources minted as `kinocut://` with schema-regression risk noted.
  7. **Restructured distribution into Parallel Track P** — C2PA (PT.1) + current-tools repurposing skill (PT.2) run kernel-independent from Phase 0; C2PA removed from Phase 4; added a calendar table. ADR alternatives now steelman disciplined-Option-B and record Track P as B's best idea absorbed into C. Risk 3, Pre-Mortem #1–2, and Open Questions updated to match.
- **Rev 3 (2026-07-10, Planner — post-Critic ITERATE; reconciled with the shipped `video_workflow_*` release, master +47 commits):** incorporated all 9 required fixes.
  1. **Reconciled the kernel with the shipping `video_workflow_*` engine** — new "Relationship to the shipping `video_workflow_*` engine" subsection in Phase 1: kernel **wraps** (not supersedes) `video_workflow_render`; `render_submit` reuses the existing spec-hash/per-step-hash resume cursor; P1.4 receipt lineage **extends the `receipt_kind:"workflow"` schema**. Answers the executor's "which resume mechanism?" — build ON the shipped one. Phase 1 shrinks to "wrap + async + durable project identity + receipt lineage."
  2. **Corrected Driver 1** — the gap is no durable project identity / no revisions-undo-branch / no cross-session edit state / no async submission; resume already exists within a single workflow spec.
  3. **Renumbered the kernel ADR** to `docs/adr/0008-editing-kernel.md` (0007 = the shipped workflow-engine ADR). Swept ADR refs.
  4. **Fixed the tool count** — post-release surface is **124 MCP tools + 103 CLI commands**; swept every stale "119"; exact counts deferred to P0.5 verification against `test_public_surface.py`.
  5. **P1.0 now states** CONTEXT.md's "project" avoid-list entry is deliberately **AMENDED, not violated**.
  6. **Hardened Phase-2 acceptance to falsifiable thresholds** — deterministic selection set, SSIM ≥ 0.98 render stability (not byte-equality, per the shipped honest-determinism note), face-centroid in safe-area ≥ 95%, caption timing ≤ 80 ms.
  7. **Test Strategy** — named `test_public_surface.py` exact-count drift as a required per-phase manifest-update step + per-tool round-trip guard.
  8. **Stated async/sync coexistence** — `render_submit` (poll-first async) wraps and coexists with synchronous `video_workflow_render`; intent verbs route durable/long-form to async; sync not deprecated.
  9. **Folded both Architect advisories** — (a) Phase-2 b-roll proposals anchor to `time_range` only until P3.0 adds node IDs; (b) transcribe/highlight-detect/scene-detect are CAS artifact producers, not timeline mutations, so excluded from the P1.6 bridge set.
- **Rev 4 (2026-07-10, release cutover):** recorded the merged repository/code rename, canonical `kinocut/` paths, the verified 135 MCP / 114 CLI surface, and the remaining Phase 0 publication/registry/site gates. Historical counts in Rev 1-3 remain part of the decision record.

## Consensus Outcome (2026-07-10)
**CRITIC VERDICT: APPROVE** (Rev 3; loop converged in 3 rounds: Architect SOUND-WITH-CHANGES → Rev 2 → Architect SOUND + Critic ITERATE → Rev 3 → Architect delta SOUND + Critic APPROVE). **Simon approved the plan on 2026-07-10.** Phase 0 is in progress; post-Phase-0 implementation remains blocked until the release-cutover exit criteria above are verified.

**Approval conditions (build-time pins, recorded by the Critic — bind at P1.0/Phase-2 build):**
1. **keep_intermediates pin (P1.0, MUST):** the detached render runner invokes workflow render with `keep_intermediates` ON, and the kill-and-relaunch acceptance test asserts completed stages are SKIPPED (stage-hash unchanged / no re-execution), not merely that the job completes — otherwise resume silently degrades to full-restart while the test still passes.
2. **Second adversarial fixture (Phase 2, MUST):** add a motion/multi-speaker fixture alongside the golden talking-head; evaluate SSIM per-FFmpeg-build (known CI gap 6.1.1 vs 8.1) so thresholds measure generalization, not single-clip overfit.

**Cosmetic sweep:** resolved in Rev 4; current source paths, counts, and tool-number references now match the renamed repository.

## Appendix A — Per-primitive Epoch sizing (required before P1.x issues open; done 2026-07-10)

AI-native hours (agent-fleet execution), from Epoch reference-class forecasting
(404-sample feature baseline, 0.65 correction). Bands are corrected→raw; the agent
opening each issue re-runs Epoch against its own profile and records the actual.

| Item | Class | Sized |
|---|---|---|
| P1.1 durable edit-project repository | feature/medium/3 | **1.3–2h** |
| P1.2 job store + detached render runner + startup reconcile | feature/large/4 | **3.9–6h** (largest single risk; the reconcile test is the acceptance keystone) |
| P1.3 content-addressed store (cache keys + reachability GC) | feature/large/4 | **3.9–6h** (correctness-critical: a wrong cache key silently serves stale renders) |
| P1.4 receipt lineage (extends workflow receipt) | feature/medium/2 | **~1–1.5h** |
| P1.5 minimal event poll | feature/small/2 | **0.3–0.4h** |
| P1.6 compat bridge (repurposing slice) | feature/medium/3 | **1.3–2h** |
| **Phase 1 total** | | **~12–18h AI-native** |

Phase-level coarse bands (same method, for the calendar): Phase 2 ≈ 15–25h
(10 medium items, P2.6 semantic index is the large one); Phase 3 ≈ 15–22h
(P3.0 is large/5 — the IR + revision DAG dominates); Phase 4 ≈ 8–14h.
These are execution hours, not wall-clock: review loops, CI, and human gates
dominate the calendar.

## Appendix B — Open questions: proposed defaults (decide/ratify at P1.0)

Recorded so no implementer stalls; each is a PROPOSAL pending the P1.0 ADR unless
Simon overrides earlier.

1. **`edit_project` API noun vs user-facing alias** → propose: API noun stays
   `edit_project_*`; no user-facing alias in v1 (verbs hide it anyway).
2. **Artifact-retention budget** → propose: default CAS budget 20 GB per managed
   project dir, reachability-GC to 80% on breach, `kino gc` manual override;
   budget configurable via env. Rationale: bounded by default, local-first, no
   silent unbounded disk growth (the class of complaint that kills local tools).
3. **Allowed VLM providers (Phase 3 vision QC)** → propose: provider-agnostic
   adapter with local-first default (Qwen-VL-class via ollama/llama.cpp when
   present), cloud keys opt-in per invocation, never required — metric floor
   already guaranteed offline. No provider allowlist baked into code; policy
   lives in config.
4. **Remote render-runner trust boundary** → propose: out of scope until a
   product path needs it (matches "local-first, no daemon"); revisit when/if a
   distributed-render issue is opened. Do not design for it in P1.2.
