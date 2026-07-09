# Agent Workflow Engine

The workflow engine lets an agent **plan, validate, render, recover, and prove** a
multi-step local video job from a single JSON job-spec, through MCP, the CLI, or the
Python client. It is the agent-native spine of the release: a small, allowlisted set
of operations wired to the same vetted engine functions the individual tools use, with
provenance receipts strong enough for another agent or a human to trust before *and*
after a render.

Four surfaces, one behaviour:

| Capability | MCP tool | CLI command | Python client |
|---|---|---|---|
| Structural gate, no render | `video_workflow_validate` | `workflow-validate` | `Client.workflow_validate` |
| Dry-run plan artifact | `video_workflow_plan` | `workflow-plan` | `Client.workflow_plan` |
| Execute + provenance receipt | `video_workflow_render` | `workflow-render` | `Client.workflow_render` |
| Summarize any receipt | `video_workflow_inspect` | `workflow-inspect` | `Client.workflow_inspect` |

Everything fails **closed**: any structural violation raises `MCPVideoError` with a
specific `code` and a `suggested_action`, and nothing unsupported silently degrades.

---

## Job-spec schema (`schema_version: 1`)

A job-spec is a JSON object. `steps` is an **ordered list** executed top-to-bottom; a
step may reference only **already-declared** sources and the outputs of **strictly
earlier** steps (backward-reference-only — there is no DAG, no cycles, no parallelism).

```json
{
  "schema_version": 1,
  "name": "captioned-vertical-short",
  "sources": {
    "hero": { "path": "input/hero.mp4" }
  },
  "steps": [
    { "id": "probe-hero", "op": "probe", "inputs": { "src": "@sources.hero" } },
    { "id": "trim-hero",  "op": "trim",  "inputs": { "src": "@sources.hero" },
      "params": { "start": 0, "duration": 6 }, "output": "@work/hero_trim.mp4" },
    { "id": "vertical",   "op": "resize", "inputs": { "src": "@work/hero_trim.mp4" },
      "params": { "width": 1080, "height": 1920 }, "output": "@work/hero_vertical.mp4" },
    { "id": "caption",    "op": "add_text", "inputs": { "src": "@work/hero_vertical.mp4" },
      "params": { "text": "Watch this", "position": "bottom-center" }, "output": "@outputs.master" }
  ],
  "outputs": { "master": { "path": "output/final.mp4" } },
  "variants": [
    { "id": "square", "overrides": { "steps.vertical.params": { "width": 1080, "height": 1080 } } }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Must be `1`. Any other value fails closed (`invalid_workflow_spec`). |
| `name` | no | Human/agent label, echoed into every artifact. |
| `sources` | yes | Map of `<id>` → `{ "path": "<relative-path>" }`. Referenced as `@sources.<id>`. |
| `steps` | yes (≥1) | Ordered list of operations (see below). |
| `outputs` | no | Map of `<id>` → `{ "path": "<relative-path>" }`. A step writes to `@outputs.<id>`. |
| `variants` | no | Batch overrides that emit N distinct outputs from one declaration. |

Unknown top-level keys, unknown step/source/output keys, and unknown variant keys are
all rejected (the models are strict — `extra="forbid"`).

### Steps

```json
{ "id": "trim-hero", "op": "trim", "inputs": { "src": "@sources.hero" },
  "params": { "start": 0, "duration": 6 }, "output": "@work/hero_trim.mp4" }
```

- `id` — unique, non-empty string; duplicates fail closed.
- `op` — one of the six allowlisted ops (below). Anything else → `unsupported_workflow_op`.
- `inputs` — exactly the input key the op expects: `src` for single-input ops, `srcs`
  (a non-empty list of refs) for multi-input `merge`. Any other input key fails closed.
- `params` — tunable knobs passed through to the backing engine. The accepted set is
  **derived from the engine's real signature by introspection** (there is no parallel,
  hand-maintained param schema). A param the engine does not accept →
  `invalid_workflow_params`. Param *value* correctness stays the engine's job at render
  time.
- `output` — `@work/<name>` (an intermediate) or `@outputs.<id>` (a declared final
  target). Required for output-producing ops; must be **absent** for the inspection-only
  `probe` op.

### Op allowlist (6 ops)

Every op maps 1:1 to an existing vetted engine function. `params` are whatever that
engine accepts.

| `op` | Backing engine | Input key | Output | Typical params |
|---|---|---|---|---|
| `probe` | `probe` | `src` | none (inspection) | — |
| `trim` | `trim` | `src` | required | `start`, `duration`, `end` |
| `resize` | `resize` | `src` | required | `width`, `height`, `aspect_ratio`, `quality` |
| `convert` | `convert` | `src` | required | `format`, `quality` |
| `add_text` | `add_text` | `src` | required | `text`, `position`, `size`, `color`, … |
| `merge` | `merge` | `srcs` (list) | required | `transitions`, `transition_duration` |

`composite_layers` is **not** a workflow op this release (call `video_composite_layers`
directly). See [Deferrals](#deferrals).

**Param values are type-checked.** Each `params` value is validated against the backing
engine's parameter type (e.g. `width` must be an integer, not `"20000"`); a type mismatch
fails closed with `invalid_workflow_params` before any render. `add_text`'s `font` is a
path-typed parameter and is **not** tunable via a workflow this release (it fails closed
as an unaccepted param); set fonts by calling `add_text` directly.

**Resource caps (fail closed).** A spec may declare at most **64 steps** and **32
variants**; `resize` dimensions are capped at 7680px. Exceeding a cap fails closed
(`invalid_workflow_spec`).

### Symbolic references (`@refs`)

Media is referenced symbolically, never by an out-of-workspace absolute path:

- `@sources.<id>` — a declared source. Undeclared → `unknown_workflow_ref`.
- `@work/<name>` — an intermediate produced by a **strictly earlier** step. A forward
  reference or an undeclared name → `unknown_workflow_ref`.
- `@outputs.<id>` — a declared output **target** (only valid as a step `output`, never as
  a step input).
- A raw relative path is accepted only if it resolves **inside the spec's workspace
  root** (the spec file's own directory). Absolute paths, `../` escapes, and symlink
  escapes fail closed with `unsafe_workflow_source`.

`merge` takes a list: `"inputs": { "srcs": ["@work/a.mp4", "@work/b.mp4"] }`. Every
element is resolved under the same backward-reference rule; any bad element fails the
whole step closed.

---

## Variants (batch grammar)

`variants[]` reuse the single `sources`/`steps`/`outputs` declaration to emit N distinct
outputs without duplicating sources. Each variant is `{ "id": ..., "overrides": {...} }`
using a small dotted-key grammar; anything else fails closed (`invalid_workflow_variant`):

| Override key | Value | Effect |
|---|---|---|
| `steps.<id>.params` | object | Shallow-merged into that step's params. |
| `steps.<id>.params.<name>` | any | Sets one param on that step. |
| `steps.<id>.output` | string | Replaces that step's output target. |
| `outputs.<id>.path` | string | Replaces that declared output path. |

**Auto output naming:** unless a variant overrides an output's `path` explicitly, each
declared output path is suffixed with the variant id, so N variants land in N distinct
files: `output/final.mp4` → `output/final.square.mp4` for variant `square`.

Source declarations are never a valid override target — variants reuse them verbatim.
Unknown param *names* introduced by an override are not silently accepted: post-merge
validation re-runs the engine-signature introspection and rejects them, so the
"introspection still enforced" guarantee holds for variants too.

- `workflow-validate` (no `--variant`) validates the base spec **and** test-merges every
  declared variant, so a malformed override is caught before any render.
- `workflow-plan --variant <id>` / `workflow-render --variant <id>` operate on that one
  variant's effective (post-override) steps and record `workflow.variant`.
- `workflow-render --all-variants` renders every declared variant in turn and returns a
  `workflow_batch` summary (one receipt per variant, each into its own `@work` dir).
  `--variant` and `--all-variants` are mutually exclusive.

---

## Resume semantics

`workflow-render --resume <receipt.json>` continues a job that previously **failed with
its intermediates kept**. Resume is precise and fail-closed:

1. **spec_hash gate** — the current spec's hash must equal the receipt's `spec_hash`; a
   changed spec is a different job (`resume_spec_mismatch`). Re-run without `--resume` to
   start fresh.
2. **variant gate** — the receipt's `workflow.variant` must equal the requested
   `--variant` (`resume_variant_mismatch`); resume each variant against its own receipt.
3. **skip-iff-all-match** — a step is skipped (reused) only when **all** hold: its prior
   status is `completed`, its recorded input hashes still match, and — for
   output-producing ops — its recorded output file still exists and **re-hashes to the
   recorded `output_hash`**. `probe` (no output) is reusable on an input-hash match alone.
4. **first-fail = resume point** — the first step failing any check, and every step after
   it, re-runs. The resumed receipt records `feature_flags.resume_used: true` and
   `feature_flags.resumed_from`.

> These hashes are **integrity checks on persisted intermediates, never byte-determinism
> claims.** Resume re-hashes each kept intermediate to decide skips (a linear read over
> intermediate sizes), so resume on large intermediates pays a real I/O cost by design.

Each run uses a **unique `@work/` directory** keyed by the spec-hash prefix + a run id
(e.g. `work/be2f3a9b-2effedb3/`), so cleanup or resume of one run can never touch another
run's intermediates.

---

## Cleanup policy

Intermediates live only in the run's unique `@work/` directory and their filenames carry
the `mcp_video_` stem prefix.

- **Success** → manifest-tracked intermediates are removed (`cleaned: true`, `policy:
  "clean-on-success"`).
- **Failure** → intermediates are **kept** (`cleaned: false`) so `--resume` can reuse
  them. (The recorded `policy` string stays `clean-on-success` — the retention is
  signalled by `cleaned: false`, not a distinct policy value.)
- **`--keep-intermediates`** → intermediates are retained even on success (`cleaned:
  false`, `policy: "keep-intermediates"`).

Cleanup only ever deletes files that resolve inside that run's `@work/` directory; it
never calls `video_cleanup`.

---

## Privacy

Workflow receipts and plan artifacts store **workspace-relative paths only**
(`input/…`, `output/…`, `work/…`). The engine resolves and confines every declared path
to the spec's workspace root, and step error messages are stripped of the workspace
prefix before they land in a receipt. Keep specs and any committed example receipts
relative and sanitized — never absolute home paths, usernames, or tokens. A privacy scan
(`tests/test_receipt_privacy.py`) enforces this over the committed public surfaces and
over freshly produced dry-run artifacts.

---

## Worked example

```bash
# 1. cheap structural gate (no render)
mcp-video workflow-validate --spec job.json

# 2. dry-run plan: op graph + source probes/hashes, renders zero media
mcp-video workflow-plan --spec job.json --save-plan plan.json

# 3. execute + write a provenance receipt
mcp-video workflow-render --spec job.json --save-receipt receipt.json

# 4. render every declared variant into its own receipt
mcp-video workflow-render --spec job.json --all-variants --save-receipt-dir receipts/

# 5. resume a job that failed with intermediates kept
mcp-video workflow-render --spec job.json --resume receipt.json --save-receipt receipt.json

# 6. summarize any receipt (read-only integrity re-check)
mcp-video workflow-inspect --receipt receipt.json
```

Python:

```python
from mcp_video import Client

video = Client()
video.workflow_validate("job.json")
plan = video.workflow_plan("job.json", save_plan="plan.json")
receipt = video.workflow_render("job.json", save_receipt="receipt.json")
summary = video.workflow_inspect("receipt.json")
```

A runnable spec lives in
[`examples/workflows/captioned-vertical-short/`](../examples/workflows/captioned-vertical-short/).
For the exact receipt shapes (`workflow`, `workflow_plan`, `workflow_batch`, and the
`layer_plan` v2 compositor receipt) see [VIDEO_RECEIPT.md](VIDEO_RECEIPT.md).

---

## Error codes

| `code` | Raised when |
|---|---|
| `invalid_workflow_spec` | Malformed spec: wrong `schema_version`, missing steps, unknown key, duplicate id, bad output target. |
| `unknown_workflow_ref` | A `@ref` that is undeclared, forward, or the wrong namespace for its position. |
| `unsupported_workflow_op` | A step `op` outside the six-op allowlist. |
| `unsafe_workflow_source` | An absolute path, `../` escape, symlink escape, or null byte in a path (also re-checked at execution time). |
| `invalid_workflow_params` | A step param the backing engine does not accept, or a param VALUE whose type cannot satisfy the engine (e.g. a string for an int). |
| `invalid_workflow_variant` | An unknown variant id, a malformed override key/value, or two variants writing the same output path. |
| `invalid_workflow_receipt` | `workflow-inspect`/`--resume` pointed at an unreadable/malformed receipt. |
| `resume_spec_mismatch` | `--resume` against a receipt whose `spec_hash` differs from the current spec. |
| `resume_variant_mismatch` | `--resume` against a receipt for a different variant. |
| `workflow_step_failed` | A step's engine raised an unexpected runtime error; the receipt records the failed step and intermediates are kept for `--resume`. |

Every payload also carries a `suggested_action` describing the fix. Artifact writers
(`--save-plan`, `--save-receipt`, `--save-receipt-dir`) reject unsafe targets with the
media guard's `unsafe_path` / `invalid_output_path` codes (system dirs, `../`, symlinks,
sensitive dotfiles, or overwriting a non-`.json` file).

---

## Deferrals (fail closed today)

These are intentionally out of scope this release and fail closed if requested:

- `composite_layers` as a workflow op — its nested layer-spec resolves media relative to
  its own directory, which would bypass workspace confinement and per-step hashing. A
  future version must first express nested layer sources as workflow `@refs`, keep them
  workspace-confined, hash them into `input_hashes`, and ship an escaping-source test.
- Parallel/concurrent step execution (sequential ordered list only).
- Conditional/branching steps, loops, retries-with-backoff.
- Cross-machine/distributed jobs.
- `--force` resume (a full restart-from-scratch flag); today a changed spec simply fails
  the resume gate and you re-run without `--resume`.
- Any op beyond the six allowlisted.
