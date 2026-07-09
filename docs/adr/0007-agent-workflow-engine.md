# Agent Workflow Engine + Bounded Compositor Upgrade

## Decision

Ship an agent-native release built on a new `video_workflow_*` tool family
(`validate` / `plan` / `render` / `inspect`) over a small six-op allowlist
(`probe | trim | resize | convert | merge | add_text`), each mapped 1:1 to an existing
vetted engine function with per-op params **introspected from the engine signature** over
a tiny input/output binding map (no parallel, hand-maintained param schema, no raw
filtergraph passthrough). Jobs use an ordered, backward-reference-only JSON spec and
produce a **separate workflow-receipt schema** (`receipt_kind: "workflow"`) with per-step
input/output hashes, a resume cursor, and a cleanup manifest.

Alongside it, a **bounded compositor upgrade**: full-canvas-only blend modes
(`multiply, screen, overlay, darken, lighten`) and rotation with a new `pivot` field, with
the `layer_plan` receipt bumped to `schema_version: 2`. CLI commands are flat
(`workflow-*`) to match the existing convention and the drift-count model; the public
surface moves 120 → 124 MCP tools and 99 → 103 CLI commands.

## Drivers

1. **Scope containment inside an "all-four" mandate** — choose a coherent MVP slice or
   scope explodes. The workflow engine is the spine every wedge attaches to.
2. **Mechanically-enforced public-surface drift** — `tests/test_public_surface.py` asserts
   exact tool/command counts and boots a real stdio server, so every surface change is a
   deliberate, counted edit.
3. **Compositor architecture reality** — the compositor is an `overlay`-based positioned
   pipeline, not a `blend` pipeline; the FFmpeg `blend` filter needs two same-size inputs,
   so blend ships full-canvas-only and positioned blend is deferred, fail-closed.
4. **The moat is orchestration + provable receipts**, not FFmpeg-filter breadth. A small
   allowlist with strong provenance beats a wide op set with weak trust.
5. **Honest determinism** — claim plan/spec/filtergraph/output-hash determinism and
   SSIM-threshold render stability; never claim byte-identical renders across FFmpeg
   builds.

## Alternatives considered

- **Workflow-first, compositor untouched** — rejected: leaves the compositor story stale
  and under-delivers on the release's compositor wedge.
- **Compositor-first (blend + rotation + effect routing), workflow deferred** — rejected:
  fails the agent-native thesis; effect-routing schema is high-risk and under-specified;
  "a deeper FFmpeg wrapper" is precisely what the release intent rejected.
- **Extend `video_batch` instead of a new family** — rejected: batch is one-operation-over
  -many-files with no DAG/resume/state; a multi-step job graph is a different abstraction
  and overloading batch would break its contract.
- **A single unioned/bumped receipt schema** — rejected: a single-render `layer_plan` and a
  multi-step `workflow` job (with resume cursor + cleanup manifest) have fundamentally
  different shapes; a `receipt_kind` discriminator lets each evolve independently while an
  inspecting agent still tells them apart.
- **Nested `workflow <sub>` CLI** — rejected: the entire CLI is flat, and the drift test
  counts only top-level command names.

## Why chosen

This slice uniquely satisfies the release sentence — *agents can plan, validate, render,
recover, and prove multi-step video work locally through MCP/CLI/Python, with receipts
strong enough for another agent or human to trust* — while respecting scope containment,
drift enforcement, and honest determinism. The workflow engine is the competitive spine;
the full-canvas blend + rotation upgrade is a concrete, SSIM-testable compositor win; the
receipts make trust a first-class, inspectable product feature.

## Consequences

- Larger public surface (+4 tools, +4 CLI commands, a new receipt kind, `layer_plan` v2) —
  mitigated by the drift manifest, discovery-file updates, and cross-surface parity docs.
- A new job-spec grammar to maintain — bounded by a hard op allowlist and introspected
  params (a drift-guard test asserts each adapter's accepted params ⊆ the engine
  signature), so an adapter can never advertise a param the engine rejects.
- Two receipt kinds to document and keep sanitized — bounded by the `receipt_kind`
  discriminator, legacy-tolerant inference in `video_workflow_inspect`, and a privacy-scan
  test.
- Blend integration risk on the `overlay` pipeline — bounded by full-canvas-only scope
  (positioned/scaled/masked/timed blend fails closed with `unsupported_blend_geometry`) and
  an SSIM-threshold gate rather than byte-equality.
- Resume re-hashes persisted intermediates (an integrity check, not a determinism claim),
  paying a real I/O cost on large intermediates — accepted for correctness, documented.

## Signature evolution (honest note)

The consensus plan's §4 signatures were illustrative and the shipped surface diverged from
them as the stories converged. The authoritative signatures now live in the tool/CLI/client
docs; two deltas are worth calling out so no reader trusts the sketch: (1) there is **no
`dry_run` parameter** — `video_workflow_validate` and `video_workflow_plan` ARE the dry-run
path (plan never renders media), so a separate flag would be redundant; (2)
`video_workflow_render` gained `variant`, `all_variants`, and `save_receipt_dir` (batch
variants, Story 5) alongside `resume_receipt`/`save_receipt`/`keep_intermediates`. These are
additive and fully covered by the drift manifest and parity tests.

## Follow-ups (next release)

Positioned/scaled/masked blend; per-layer effect routing (`layer.effects[]`);
mask-edge/feather semantics; audio compositing/mixing (output is video-only `-an` today);
`composite_layers` as a workflow op once nested sources are `@ref`-confined and hashed;
more workflow ops; parallel step execution via an optional `needs:` field; a `--force`
full-restart resume flag; a multi-FFmpeg-build CI matrix; signed/attested receipts.
