# Trusted Execution Editing Kernel

## Decision

Kinocut adds a durable **edit project** kernel without changing public tools. Phase-1 history is an append-only linear sequence of immutable revisions; branching, checkout, undo, Timeline-IR graphs, and render DAGs remain deferred to Phase 3. Frozen `RecordBase` contracts retain semantic `sha256:` identities and append-only supersession. Content-addressed storage adds one immutable blob per digest plus a manifest record alongside `append_record` and existing asset ingest.

Async jobs use persistent states `queued`, `running`, `succeeded`, `failed`, and `cancelled`. The later detached **render runner** (never “worker”) wraps `video_workflow_render` with `keep_intermediates=True` and reuses its spec-hash/per-step-hash resume cursor; synchronous workflow rendering remains unchanged. Receipt lineage adds `edit_project_id`, `revision_id`, `job_id`, `source_digests`, `output_digest`, and `toolchain_fingerprint`. Phase 1 admits only `revision.created`, `render.completed`, and `quality.gate.failed` events.

## Domain language and relationship

A **creation project** belongs to `creation_engine.py`; a **Hyperframes project** belongs to `hyperframes_engine.py`; an **edit project** is the durable kernel identity, using API noun `edit_project_*` without a v1 alias. A Tool follows **Tool → (Engine | kernel-compile)**: legacy tools delegate 1:1 to an Engine; durable editing paths compile typed operations into the kernel. Existing path-in/path-out tools remain compatibility adapters unless a product path graduates them.

## Consequences

Phase 1 is internal and additive, so MCP, CLI, and client surfaces do not change. Detached execution, startup reconciliation, public kernel tools, proxies, reachability GC, and repurposing adapters are later slices that must build on these contracts.
