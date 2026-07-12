# AI-video contracts (Wave 0 foundation)

> **Lifecycle status (2026-07-12):** implemented on the incomplete draft branch and under
> review. This contract documentation is not a release receipt or publication authorization.

This document describes the shared, strict, versioned record model and the
private project store that every later AI-video wave composes over. Wave 0 adds
**contracts, storage, and serialization only** — no new editing behaviour and no
public MCP/CLI/Python editing command.

All models live under `kinocut/contracts/` and are re-exported from
`kinocut.contracts` (and `kinocut` re-exports the `contracts` package). The
project store lives under `kinocut/projectstore/`.

## Record catalog

Canonical records (each subclasses `RecordBase`, is immutable, and forbids
unknown fields on write):

| Record | Module | `record_kind` |
| --- | --- | --- |
| `GenerationAcceptanceSpec` | `contracts/acceptance.py` | `generation_acceptance_spec` |
| `AssetRecord` (+ `GenerationLineage`) | `contracts/asset.py` | `asset_record` |
| `ClipVerdict` (+ `Disposition`) | `contracts/verdict.py` | `clip_verdict` |
| `DefectFinding` (+ `DefectCode`, `DefectStatus`, `Severity`) | `contracts/defect.py` | `defect_finding` |
| `ProtectedElement` (+ `ElementType`, `DurationPolicy`) | `contracts/protection.py` | `protected_element` |
| `ReviewDecision`, `KnownLimitation`, `ApprovalState` | `contracts/review.py` | `review_decision`, `known_limitation`, `approval_state` |
| `PromptOutcome`, `UsageEvent`, `CostEvent`, `WorkflowRecipe` | `contracts/learning.py` | `prompt_outcome`, `usage_event`, `cost_event`, `workflow_recipe` |

Embedded value objects (no independent id): `NormalizedRegion`, `Measurement`,
`IntegrityResult`, `SeverityThreshold`, `ParameterSlot`, plus the receipt and
capability value objects below.

Receipt + capability contracts:

| Contract | Module |
| --- | --- |
| `AiVideoReceiptSection`, `OrderedInput`, `Transformation`, `PreservationProof`, `PreservationVerdict` | `contracts/receipt_ai_video.py` |
| `CapabilityReport`, `NextAction`, `SurfaceAvailability`, `AvailabilityState` | `contracts/capability.py` |

## ID rules

- **`record_id`** is `"sha256:" + sha256(canonical semantic JSON)`. Informational
  fields (`created_at`) are excluded; `record_id` itself is excluded. Serialization
  is sorted-key, compact-separator, `ensure_ascii=False`, `allow_nan=False`.
  Computed by `canonical_record_id(model)`, which accepts only a `RecordBase`,
  allows informational-only exclusions, and maps unencodable content to a stable
  `MCPVideoError`.
- **`asset_id`** is `"sha256:" + sha256(original bytes)`.
- **`Sha256` / `AssetId`** are `sha256:<64 lowercase hex>`.
- A supplied `record_id` is never trusted: it must equal the recomputed canonical
  digest or the record is rejected.

## Private project store

Layout under a project's `.kinocut/`:

- `records/<kind>.jsonl` — append-only canonical records, one JSON line each.
- `assets/sha256/<digest>/<sanitized-name>` — content-addressed asset bytes.
- `indexes/` — disposable, rebuildable id manifests.
- `locks/`, `observations/` — internal.

Guarantees (`kinocut/projectstore/`):

- **Content-addressed** — identical bytes resolve to one location; `ingest_asset`
  is idempotent by digest and copies bytes in a single-lock, single-pass
  hash+copy (`O_NOFOLLOW`, atomic install).
- **Append-only** — corrections *supersede* by `record_id`; history is never
  rewritten. Supersession requires exactly one existing, same-project,
  not-yet-superseded target, and must not form a cycle.
- **Lock-guarded & atomic** — every mutation holds an exclusive project lock and
  swaps files with a secure temp (`mkstemp`) + `fsync` + `os.replace` + dir
  `fsync`, with all-or-nothing rollback. `rebuild_indexes` stages the whole set
  and swaps it transactionally.
- **Exact-type write boundary** — each record is re-validated through its
  `record_kind`-bound concrete model (subclasses and duplicate ids are rejected).

## Privacy

- Stored records carry **project-relative paths only** — never home paths,
  usernames, absolute host paths, or raw prompt text (provenance is stored by
  hash).
- Every public store/adapter boundary maps raw `OSError` / `UnicodeError` /
  `JSONDecodeError` / Pydantic errors to a stable, privacy-safe `MCPVideoError`
  (`invalid_record`, `unknown_record_field`, `record_supersession_cycle`).
- Receipt identity fields (`role`, `tool`, `operation`, `method`, `expected`,
  `duration_policy`, `project_id`, `toolchain_versions`, `warnings`) are **closed
  bounded codes** (`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$`) so arbitrary prose,
  host paths, URLs, and secrets are structurally unrepresentable.

## Reader migrations

Records are written strictly at the current schema version (`1`). Readers may
encounter documented older records: `kinocut/projectstore/_migrations.py` holds
an explicit `(record_kind, from_version)` registry applied **only on read**.
Migration deep-copies its input (nested structures never leak), requires a dict
result, and maps any migrator fault to `invalid_record`. An older version with no
registered migrator, an unknown kind, an unknown field, or a future version fails
closed.

## Additive `ai_video` receipt section

`AiVideoReceiptSection` is attached to a legacy receipt under a single nested
`ai_video` key via `attach_ai_video_section(receipt, section)`, which deep-copies
the receipt, refuses to clobber an existing section, and never mutates any legacy
top-level field. `read_ai_video_section(receipt)` returns the typed section,
`None` when absent, or a stable `MCPVideoError` when malformed. Every existing
receipt kind (`workflow`, `workflow_batch`, `rescue`, `rescue_plan`, `layer_plan`)
still parses through `inspect_receipt` and reads as section-absent.

## Capability and approval boundaries

- `CapabilityReport` is a **structured** contract (bounded capability id,
  per-surface `SurfaceAvailability`, bounded format/dependency codes, closed
  `AvailabilityState`), not help text. A `reason_code` is required iff the
  capability is not fully available.
- `NextAction` is **advisory only**: an action code, a short summary, at most one
  bounded sanitized `kino …` command *template* that can never carry a real path,
  shell metacharacter, or execute, and the record ids blocking it. There is no
  execution hook.
- `ApprovalState.is_publishable(resolved_decisions, resolved_approval_states, *, blocking_findings)`
  derives publishability and never stores a boolean. It fails closed unless: the
  state is `approved`, not superseded (by field or a valid history graph), with no
  invalidation reasons or blocking findings; the candidate and every required
  artifact passed integrity with no conflicting result; and every required human
  decision is a fresh, human `approve` bound to the exact candidate and dependency
  fingerprint (identities are recomputed; forged/duplicate/subclass evidence fails
  closed).

## Boundaries respected in Wave 0

No public MCP/CLI/Python editing command is added; no version bump, tag, publish,
submission, deploy, or release; no migrations beyond the read-only registry.
