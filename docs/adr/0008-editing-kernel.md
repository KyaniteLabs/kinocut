# Trusted Execution Editing Kernel

## Decision

Kinocut adds a durable **edit project** kernel without changing public tools. Phase-1 history is an append-only linear sequence of immutable revisions; branching, checkout, undo, Timeline-IR graphs, and render DAGs remain deferred to Phase 3. Frozen `RecordBase` contracts retain semantic `sha256:` identities and append-only supersession. Content-addressed storage adds one immutable blob per digest plus a manifest record alongside `append_record` and existing asset ingest.

Async jobs use persistent states `queued`, `running`, `succeeded`, `failed`, and `cancelled`. The later detached **render runner** (never “worker”) wraps `video_workflow_render` with `keep_intermediates=True` and reuses its spec-hash/per-step-hash resume cursor; synchronous workflow rendering remains unchanged. Receipt lineage adds `edit_project_id`, `revision_id`, `job_id`, `source_digests`, `output_digest`, and `toolchain_fingerprint`. Phase 1 admits only `revision.created`, `render.completed`, and `quality.gate.failed` events.

## Domain language and relationship

A **creation project** belongs to `creation_engine.py`; a **Hyperframes project** belongs to `hyperframes_engine.py`; an **edit project** is the durable kernel identity, using API noun `edit_project_*` without a v1 alias. A Tool follows **Tool → (Engine | kernel-compile)**: legacy tools delegate 1:1 to an Engine; durable editing paths compile typed operations into the kernel. Existing path-in/path-out tools remain compatibility adapters unless a product path graduates them.

## Consequences

Phase 1 is internal and additive, so MCP, CLI, and client surfaces do not change. Detached execution, startup reconciliation, public kernel tools, proxies, reachability GC, and repurposing adapters are later slices that must build on these contracts.

## CAS restoration clarification

An immutable CAS manifest records identity, not perpetual availability. Collection
receipts remain append-only. Re-ingesting collected, missing or corrupt bytes keeps
the original manifest and records a `cas_blob_lifecycle` restoration intent before
installing bytes, followed by a completion after installation and directory fsync.
Per-digest supersession and explicit references to the latest deleting GC receipt
define availability across independently ordered record logs; timestamps never do.
A later collection invalidates earlier restoration. GC receipts reference the
current lifecycle heads so repeated collection generations have distinct semantic
identities. An interrupted restoration remains unavailable on reopen, even if its
bytes are already correct, and re-ingestion can safely finish a new recorded repair.
This is an internal additive record kind; no public tool or manifest schema changes.
Repair intents also record bounded private backup locations before moving old
bytes. Retry and collection remove only those recorded owned files. Collection
budgets use observed canonical/backup byte sizes and can reclaim unreachable
pending installations; reachable sources remain protected even during repair.

## Detached render cancellation clarification

Queued cancellation is immediate. A running cancellation first appends a
`running` snapshot with `stage: cancellation_requested`, retaining its runner
PID. Termination similarly uses `stage: termination_requested`; an outstanding
cancellation keeps its meaning if termination is retried. These request snapshots
change existing stage metadata, without extending hashed record schemas or states.
The external controller never signals a recorded PID. A dedicated worker validates
a RUNNING journal head naming its own live PID and consumes stop intent by signaling
only its own private group/session. Forked copies and mismatched identities cannot
acquire stop authority. Bounded verification runs outside the project lock; an
unwatched or unresponsive legacy worker stays pending rather than receiving an
unsafe external force kill.

Worker-scoped POSIX command guardians inherit the job lease and own a liveness
pipe. Worker death stops each guardian's own live group. Confirmed cancellation
requires both no executing worker-group members and a released inherited lease.
Reconciliation uses the same proof and never treats a missing or negative caller
liveness hint as proof that descendants stopped. Linux ignores zombie-only groups;
other platforms conservatively require group disappearance. Normal commands are
reaped, while abnormal zombies still require host PID1 reaping. Windows commands
retain kill-on-close Job ownership. These controls are local execution evidence,
not a sandbox, cryptographic identity guarantee or lease on output paths.

The runner observes a pre-start request before invoking the engine, and racing
success/failure cannot replace pending stop ownership. No public hashed journal
schema or state is added by this repair.

The [Projectstore lifecycle guide](../PROJECTSTORE_LIFECYCLE.md) records current
helper return values, repair ownership, conservative reconciliation, platform
limits and focused validation without replacing this decision's original scope.
