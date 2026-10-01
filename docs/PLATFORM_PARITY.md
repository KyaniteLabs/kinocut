# Platform parity: current support and proposed service architecture

This development checkout improves operator parity across local MCP, CLI, and
Python interfaces. It does not implement mobile apps or a hosted processing
service. Published 1.15.3 has **201 MCP tools / 173 CLI commands**; development
has **203 / 177**. Public counts do not establish backend availability or quality.

## Current support and evidence

| Journey | Implemented support | Limits and source evidence |
| --- | --- | --- |
| Windows, macOS, Linux | Local Python package, CLI and stdio MCP; cross-platform MCPB validation matrix | FFmpeg and optional engines must be installed. [Packaging matrix](../.github/workflows/mcpb.yml), [dependencies](../pyproject.toml), [diagnostics](../kinocut/doctor.py). Matrix configuration is not proof every optional engine works on every host. |
| MCP agent | Local tool execution and structured results | [`kino --mcp`](../kinocut/__main__.py) calls `mcp.run()` with its default stdio transport. [App construction](../kinocut/server_app.py) does not configure a service authentication boundary. |
| CLI operator | Local editing, planning, QC and review adapters | [Parser](../kinocut/cli/parser/__init__.py), [handlers](../kinocut/cli/handlers_intent.py). Development adds `mix-audio`, `duck-audio`, `record-motion-acceptance`, `hls-segment`, and controls on existing commands. |
| Python pipeline | Direct in-process engine adapters | [Client](../kinocut/client/__init__.py), [base](../kinocut/client/base.py). This is not a remote-service SDK. |
| Browser | Static video/timeline review HTML | [Review surface](../kinocut/multipliers/review_ui.py). No complete upload/edit/render application or authenticated processing service is implemented here. |
| Android and iOS | No native client implementation identified in repository inspection | Python/FFmpeg/Node/optional AI requirements do not establish arbitrary native execution on a phone. |
| Remote processing | Immutable egress, retention, approval, selection and receipt contracts | [Remote API](../kinocut/remote/api.py) and [adapters](../kinocut/remote/adapters.py) explicitly implement fake-only mapping. Real upload, provider execution and shared worker/client journeys remain unimplemented. |

Development also exposes `video_mix_audio` and `video_record_motion_acceptance`.
Frame extraction uses the same omitted-timestamp policy across interfaces;
CLI goal/source compilation and explicit 360 review use existing shared engines.
The estimator in [Client](../kinocut/client/estimates.py), MCP
`video_estimate_operation`, and CLI `estimate` calls the same local oracle.
See [CLI reference](CLI_REFERENCE.md), [tools](TOOLS.md), and
[quality evidence](QUALITY_EVIDENCE.md) for exact semantics.

## Architecture decision

Use a shared processing service for browser, Android and iOS clients. Keep
optional desktop-local execution for offline work, privacy and capable hardware.
Both execution paths should consume the same versioned operation specifications,
export profiles, receipts and quality rules. Mobile interfaces control jobs and
review artifacts; they need not run the entire processing stack on-device.

Prefer a responsive browser client first. Add native mobile shells only where
background transfer, file sharing or device integration warrants them. Backend
choice must remain explicit: local and remote execution have different transfer,
retention, availability and cost implications. Discovery must identify unavailable
operations before submission, rather than imply a dependency is installed because
a public method exists. The current [capability catalog](../kinocut/capability_report.py)
is a useful starting point but covers only six broad capabilities.

## Feature and quality contract

Parity means equivalent supported operations and parameters, source identity,
timing/audio/caption behavior, export specifications, failure semantics, QC,
receipts and human review gates. It does not mean identical latency, cost or
encoded bytes on different hardware. Where hardware codecs or platform playback
differ, compare decoded outputs against agreed tolerances and declare limitations.

Pin engine, model, font and export-profile versions. Use the same canonical
fixtures and approved plans across interfaces. Verify duration, frame count,
dimensions, picture/audio origin, caption placement, loudness, decode integrity,
source hashes and required review decisions. Do not equate objective QC or model
sampling with whole-film human viewing. Motion acceptance records an explicit
caller attestation; it remains unverified by the system and is not release approval.

## Reuse and missing boundaries

Reuse [workflow specifications/execution](../kinocut/workflow/executor.py),
[CAS ingestion](../kinocut/projectstore/cas.py), append-only
[project records](../kinocut/projectstore/store.py), and durable local
[jobs](../kinocut/projectstore/render_jobs.py). Submission, polling, cancellation,
resumption and detached runners already exist locally. They are not a distributed
queue, tenant isolation or authenticated job ownership.

The generic [input validator](../kinocut/ffmpeg_helpers.py) resolves readable host
paths; it does not confine callers to an authenticated workspace. Workflow artifact
[confinement](../kinocut/workflow/planner.py) and store symlink guards help protect
local execution but do not authorize users. A service must accept owned project
and asset IDs, resolve them to private worker paths, and enforce authorization
for every upload, job, progress event and download. Never pass arbitrary remote
caller paths directly into the local tool registry.

Missing service work includes authentication, project authorization, resumable
staged uploads, isolated bounded workers, actual queue scheduling, idempotent
requests, quotas, progress/reconnection, cancellation, artifact retrieval,
retention/deletion, failure recovery and measured resource billing. Reuse the
remote approval/egress contracts without treating fake adapters as working
network execution. No public exposure or deployment is part of this document.

## Latency and cost evidence

Measure upload, queue, inspection, preview readiness, render, QC, download and
total user-visible time separately. Record cold/warm p50/p95, sample counts,
failures and confidence limits on named hardware, codecs and networks. Include
short 1080p, longer 4K, stitched 360, transcription and heavy optional AI jobs,
plus constrained mobile links and concurrent demand. Small fixtures verify
correctness; they do not predict production throughput.

For monetary expectations, measure CPU/GPU runtime, memory, temporary storage,
retained GB-days, ingress/egress, external-provider charges and retries; apply
actual dated provider prices. Desktop costs depend on owned hardware and energy.
The [cost oracle](../kinocut/te/cost_oracle.py) returns dimensionless local
heuristics with `currency=null`, not cloud invoices or validated service timings.
[Golden-path timings](status/golden-path-timings.md) provide baseline scaffolding;
historical [performance reports](status/perf-committee/README.md) explicitly warn
against implementing stale recommendations.

## Bounded implementation phases

1. Inventory/version operations, dependency eligibility, export/QC contracts and
   representative fixtures. Identify supported and unavailable combinations.
   Establish local baselines and cross-interface regression checks.
2. Build a private service adapter and remote SDK contract around shared workflows
   and jobs. Validate ownership, path confinement, uploads, idempotency,
   cancellation, recovery and resource limits with local requests. Exercise
   cross-project access denial and interrupted transfers before exposure.
3. Implement browser ingest → inspect → plan → render → QC → human review →
   download. Add mobile transfer/restart/sharing behavior against the same
   contracts. Keep source-bound approval and actual human inputs explicit.
4. Add desktop local/service selection and remote MCP/CLI/Python adapters.
   Publish performance/cost expectations only after representative end-to-end
   measurement and versioned quality acceptance. Deployment is separate work.

Completion of local operator additions satisfies neither service readiness nor
mobile/browser parity. Those journeys require the implementation and evidence
above before they can be advertised as supported.
