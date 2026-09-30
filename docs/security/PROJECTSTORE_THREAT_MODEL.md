# Projectstore and detached-runner threat model

Status: reviewed for the Phase 1–2 exit on 2026-07-27.

Current-development clarification: CAS restoration and detached cancellation
controls below include the lifecycle fixes documented in
[Projectstore lifecycle](../PROJECTSTORE_LIFECYCLE.md). The historical review
date is not a release receipt for these additional changes.

## Scope and trust boundaries

The scope is `kinocut/projectstore/`: append-only records, edit revisions,
content-addressed blobs, garbage collection, frozen workflow specs, progressive
receipts, and the detached render runner. The existing synchronous
`video_workflow_render` engine remains below this boundary.

The project directory and source media are user-owned local inputs. The
projectstore protects integrity and confinement against malformed records,
symlink/path attacks, stale writers, corrupt blobs, and mistaken process
identity. It does not protect a project from the same operating-system user
deliberately rewriting files, and it is not an authentication or OS sandbox.
The detached runner has the invoking user's privileges.

`kinocut://` job resources remain a design namespace, not an authorization
boundary. No job-resource handler is currently registered, so the system must
not claim resource URI authorization that does not exist.

## Threat review

| Threat | Control and evidence | Residual risk |
| --- | --- | --- |
| Job-store record tampering or truncation | Canonical record identities, strict model validation, append-only successor chains, supersession validation, corruption-to-contract-error behavior, and atomic rollback. See `tests/test_projectstore_security.py`, `tests/test_projectstore_hardening.py`, and `tests/test_projectstore_edit_projects.py`. | A malicious same-user rewrite is detectable when it violates identities or chains, but there is no signature/MAC against a fully rewritten consistent store. Backups remain an operator responsibility. |
| Symlink or path traversal through records, specs, receipts, indexes, or blobs | Project-relative normalized locations, symlink rejection, safe-target resolution, atomic no-follow writes, and privacy-safe errors. See `tests/test_projectstore_security.py`, `tests/test_projectstore_hardening.py`, `tests/test_projectstore_render_jobs.py`, and `tests/test_projectstore_cas.py`. | The project root itself is user-selected and therefore trusted as the containment root. |
| Forged CAS digest, corrupt blob, or unsafe garbage collection | Resolution checks availability history and rehashes bytes under the project lock. Re-import preserves immutable manifests/GC history and appends repair intent/completion; interrupted repair remains unavailable. GC roots include heads, branches, revision sources and compiled inputs, and observed byte accounting includes recorded repair backups. Invalid chains and cross-digest backup ownership fail closed. See `tests/test_projectstore_cas.py`, `tests/test_projectstore_cas_derived.py`, `tests/test_projectstore_cas_gc.py`, and `tests/test_projectstore_cas_lifecycle.py`. | CAS is local integrity storage, not confidential storage. Returned paths are not leased against later GC/external mutation; reachable assets and other project files can exceed the CAS budget. |
| PID reuse, reattach spoofing or false cancellation | Signaling requires a positive non-self process-group leader plus the job-specific held lease. The child waits for a RUNNING record naming its own PID before rendering. Unverified/unfinished stops retain RUNNING, request stage and PID instead of claiming completion. A confirmed stop requires no executing group members and a released lease. See `tests/test_projectstore_render_jobs.py`, `tests/test_projectstore_render_runner.py`, and `tests/test_projectstore_render_cancel.py`. | PID/lease checks are local evidence, not cryptographic identity. Reconciliation never signals a PID or treats missing/negative liveness hints as proof of descendant exit. Unsupported proof remains pending. A hostile same-user process can deny service by holding a lease. |
| Detached runner privilege expansion or shell injection | The parent uses a fixed argv, `shell=False`, a new session, closed descriptors, and detached stdio. The child opens the named project, resolves the frozen spec inside it, and wraps the existing workflow renderer. | Render operations retain normal Kinocut/FFmpeg access under the invoking user. Projectstore is not a sandbox. |
| Receipt or progress spoofing | Corrupt receipts fail closed; terminal success requires validated lineage attached to the authoritative engine receipt and persisted project/revision/job identities. See `tests/test_projectstore_render_jobs.py`, `tests/test_projectstore_render_runner.py`, and `tests/test_workflow_receipt_lineage.py`. | Progressive receipt files are not signed against malicious same-user replacement. |
| Resource URI cross-project access | No `kinocut://jobs/...` resource handler is shipped, so there is currently no resolver to attack or authorize. A future handler must bind a resource request to an explicitly opened project, validate the job identity in that store, and use the same safe-target rules. | Registration without those checks is a release blocker and requires new cross-project denial tests. |
| Secret or host-path disclosure | Persisted job records use project-relative spec/receipt paths; mapped errors avoid embedding supplied secret paths; detached stdio is discarded. Privacy tests cover malformed paths and receipts. | Rendered media and user-authored workflow content are intentionally readable to the invoking user. |

## Adversarial exit gate

The Phase 1–2 projectstore kernel is approved for its stated local integrity
boundary when the following command is green:

```bash
python3 -m pytest \
  tests/test_projectstore_security.py \
  tests/test_projectstore_hardening.py \
  tests/test_projectstore_cas.py \
  tests/test_projectstore_cas_derived.py \
  tests/test_projectstore_cas_gc.py \
  tests/test_projectstore_cas_lifecycle.py \
  tests/test_projectstore_edit_projects.py \
  tests/test_projectstore_render_jobs.py \
  tests/test_projectstore_render_runner.py \
  tests/test_projectstore_render_cancel.py \
  tests/test_workflow_receipt_lineage.py -q --tb=short
```

Any future public job resource, remote runner, shared-user store, or store
signature changes this trust boundary and requires a new review.
