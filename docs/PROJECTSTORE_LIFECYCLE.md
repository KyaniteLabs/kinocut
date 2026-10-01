# Projectstore CAS and detached-render lifecycle

This describes the Python projectstore module in the current development tree.
The helpers below do not add MCP tools or CLI commands. See
[the editing-kernel decision](adr/0008-editing-kernel.md) and
[the projectstore threat model](security/PROJECTSTORE_THREAT_MODEL.md).

## Content identity and availability

`ingest_blob(project, source_path, media_type=None)` preserves one immutable
`CASManifestRecord` per content digest. The manifest's identity, location, byte
size and original media type remain unchanged on re-import. An existing manifest
alone does not establish that its bytes are available: an ordinary cache hit
verifies the stored bytes before returning it.

`resolve_blob(project, digest)` checks the manifest, availability history and
actual digest/byte size under the project lock. It returns a verified path at that
instant; it does not lease the path against later collection or external changes.
Missing, corrupt, collected or incompletely restored bytes fail closed with
`MCPVideoError`.

Re-importing the same source repairs collected, missing or corrupt bytes while
returning the original manifest. Restoration appends records to
`.kinocut/records/cas_blob_lifecycle.jsonl`:

| State | Meaning |
| --- | --- |
| `restoring` | Durable repair intent. Resolution remains unavailable, even if replacement bytes have already been installed. |
| `available` | Completion recorded after installing the hashed source bytes and syncing the containing directory. |

Each lifecycle record names the immutable manifest and digest, supersedes the
previous record for that digest, and references the latest deleting GC receipt
when one exists. Record logs have separate append order; timestamps do not decide
which deletion or restoration wins. A new collection invalidates earlier
restoration. Old manifests, lifecycle records and GC receipts are never erased.

When old bytes need a rollback backup, its bounded project-relative location is
recorded in the intent before moving them. Completion must match that intent;
different digests cannot claim the same backup location. A failed completion
restores the prior bytes and keeps the intent unavailable. A process crash can
leave an intent, replacement bytes or a recorded backup; re-import retries a
recorded repair and removes its recorded owned backups. Reopening the project
never silently completes a pending restoration.

### Garbage collection

`collect_cas_garbage` is available from `kinocut.projectstore.cas_gc`. Its default
budget is 20 GiB. Collection counts observed canonical-blob and recorded-backup
bytes, including interrupted repairs, and evicts the oldest unreachable manifests
until it reaches 80% of the requested budget where possible.

Reachability includes edit-project/global heads, branch heads, revision source
bindings, compiled operation sources and reachable semantic indexes. Referenced
sources remain protected during repair. Opaque legacy operation hashes cause
conservative retention. If the store is under budget or has nothing safely
reclaimable, collection returns `None`.

The append-only `cas_gc` receipt records deleted digests, observed bytes freed,
retained reachable count and causal references to lifecycle heads/prior deleting
receipts. Unreachable pending installations and their recorded backups can be
reclaimed without making those bytes readable first. Collection removes only
canonical blobs and explicitly recorded repair-owned files; it does not scan and
delete unknown user files. This budget is not a hard cap on the whole project:
reachable blobs, legacy assets, workflow intermediates and other project files
can remain above it.

## Detached render jobs

`submit_render_job` freezes a validated workflow spec and records `queued`.
`start_render_job` checks that state, starts the detached runner and persists its
`running` record/PID under one project lock. Cancellation cannot mark an
unrecorded spawned runner as a cancelled queued job. The child holds the
job-specific lease and waits for a running record naming its own PID before
invoking the workflow engine.

The runner keeps workflow intermediates and reuses the existing receipt's
spec/hash-based resume cursor. Successful completion requires receipt lineage;
the succeeded record and completion event use the existing exception-atomic
append transaction. This is not a cross-file crash-atomic transaction.

### Cancellation and termination returns

`cancel_render_job` returns a `RenderJobRecord`. Check its status and stage;
returning from the call does not always mean cancellation has finished.

| Situation | Returned/stored state | Runner PID |
| --- | --- | --- |
| Queued cancellation | `cancelled`, stage `cancelled` | Cleared |
| Running cancellation with confirmed stop | `cancelled`, stage `cancelled` | Cleared |
| Running cancellation with unconfirmed stop | `running`, stage `cancellation_requested` | Retained |
| Termination with confirmed stop | `failed`, stage `failed`, code `terminated` | Cleared |
| Termination with unconfirmed stop | `running`, stage `termination_requested` | Retained |

Calling `terminate_render_job` for an outstanding cancellation preserves the
cancel request: confirmed completion becomes `cancelled`, not `failed`.
Termination of an already terminal job returns its existing record. Repeated
cancellation of a terminal job remains an illegal transition.

The controller records stop intent and waits; it never signals a reusable external
PID. The dedicated worker validates a RUNNING journal head naming its own PID,
then consumes stop intent and signals only its own live private process group.
A forked copy or mismatched group/session cannot acquire this authority. Polling
caches a validated head until the journal changes. The bounded quiescence wait
defaults to five seconds, polling every 20 milliseconds outside the project lock.
An unwatched or unresponsive legacy worker remains unconfirmed; it is never
force-killed from a recorded PID plus an inherited lease. Unconfirmed requests
retain their PID and typed stop error for retry or reconciliation.

POSIX commands launched by the dedicated worker run under a guardian that holds
the inherited job lease and staged descriptors. A parent-only liveness pipe stops
the guardian's own private group when the worker dies, including on hard kill.
Normal native commands and their guardians are reaped by their live parents.
Abnormal shutdown can leave nonexecuting zombies for host PID1 to reap; a
non-reaping host does not acquire a guarantee of zero retained PID slots.
Windows native commands use kill-on-close Job Objects. Deliberate descendant
session escapes and hostile same-user processes are outside this local boundary.

Linux verification checks that no executing members remain in the worker group;
zombie-only members cannot continue rendering. Other platforms conservatively
require process-group disappearance. All terminal stops also require the inherited
lease to be free, preventing escaped media work from being mistaken for completed
shutdown. Unsupported proof leaves the request pending.

The runner observes a pre-start request before invoking the engine. Racing
success/failure updates cannot discard stop ownership or emit a successful
completion after a request. The internal `run_job` helper may return the label
`cancelled` or `failed` to mean it is leaving execution while the stored job still
remains `running`; the controller/reconciliation owns confirmed terminal status.
Cancellation does not establish atomic publication for every workflow operation.

### Reconciliation and resume

`reconcile_render_jobs(project, is_alive=None)` never signals processes. It records
terminal status only when the group is observably quiescent and the lease is free.
An ordinary abandoned running job becomes `failed` with `orphaned_runner`;
requested cancellation becomes `cancelled`, and requested termination becomes
`failed` with `terminated`.

A positive `is_alive` hint preserves an ordinary running job. A missing or
negative hint does not prove that its descendants stopped, and cannot turn live
work into an orphan. Pending requests use actual group/lease evidence. Callers
can poll `render_job_status`, retry a pending stop or reconcile after exit:

```python
from kinocut.projectstore import cancel_render_job, reconcile_render_jobs, render_job_status

head = cancel_render_job(project, job_id)  # project and job_id are already opened/submitted
if head.status.value == "running":
    assert head.stage == "cancellation_requested"
    reconcile_render_jobs(project)       # retains the request while execution remains live
status = render_job_status(project, job_id)
```

`resume_render_job` accepts only confirmed failed/cancelled jobs and moves them
back to queued, carrying recorded progress forward. A pending stop is still
running and cannot be requeued to overlap the old execution.

## Focused validation

```bash
python3 -m pytest \
  tests/test_projectstore_cas.py \
  tests/test_projectstore_cas_gc.py \
  tests/test_projectstore_cas_lifecycle.py \
  tests/test_projectstore_render_jobs.py \
  tests/test_projectstore_render_runner.py \
  tests/test_projectstore_render_cancel.py \
  tests/test_contracts_trusted_execution.py -q --tb=short
```

Lifecycle tests cover repeated collect/re-import/reopen cycles, corruption,
record/fsync failures, actual process exits during repair, backup ownership,
concurrent ingestion/collection, verified descendant cancellation, pending PID
retention and startup/cancellation races. The real process-group tests require
Linux; focused results do not replace the repository's full validation gate.
