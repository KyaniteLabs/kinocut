# Sound S3 integration checkpoint

**Snapshot date:** 2026-07-13

**Reviewed implementation tip:** `3d881113`

**State:** implemented and verified on Niko; independently approved; unreleased

## Executive summary

This checkpoint closes S3, the dependency-critical `kinocut_sound` registry, configuration,
provider-policy, render-fingerprint, and authorization-aware cache leaf. S1-S4 are now complete.
S5 voice, S7 post/spatial, and S8 ambience are the next parallel-ready leaves.

This is an implementation checkpoint, not a release candidate. It authorizes no version bump,
tag, package upload, registry submission, deployment, release creation, or announcement.

## S3 capability surface

S3 provides:

- a sealed, code-owned adapter registry with bounded identifiers, descriptors, capability probes,
  and same-instance probe/selection;
- local-first provider selection with exact provider/region/host/credential route bindings;
- strict execution limits for bytes, duration, timeouts, retry/idempotency, cancellation,
  concurrency, rate, and redirects;
- immutable, route-bound cloud approvals with exact request, route, policy, and limit snapshots;
- version-addressable presets and project configuration joined to exact catalog and compiled
  registry identities;
- complete render fingerprints with required/advisory capability separation and bounded vectors;
  and
- explicit protected and unprotected cache paths with exact cloud scope, content-digest checks,
  and real S2 consent-ledger lineage.

## Adversarial hardening

Independent reviews forced the S3 boundary to close the following concrete defects:

- dishonest mapping lengths, hostile descriptor/probe results, and probe/selection instance drift;
- cross-product provider authorization and cloud construction on an available local path;
- incomplete or role-spoofed render fingerprints and unbounded capability/toolchain vectors;
- caller-controlled protected lineage, missing unprotected cache semantics, and absent artifact
  content verification;
- non-versioned presets and configuration not joined to exact catalog/registry state;
- dotted import/class-shaped adapter identifiers;
- hostile constructed Pydantic policy/request objects bypassing strict booleans and limits;
- cloud approvals not bound to exact route, request, policy, retention, territory, and limits;
- an incorrect S2 `ConsentLedger.commit_lease` integration signature; and
- coherent `model_copy()` approval forgery, closed by binding process-local issuance proof to the
  full canonical approval payload and rejecting changed or rehydrated approvals.

## Verification receipt

- Focused S3 tests: **53 passed**.
- All `kinocut_sound` tests: **290 passed**.
- Architecture and centralization tests: **22 passed**.
- Serialized full repository suite: **3677 passed, 18 skipped, 8 warnings in 607.76s**.
- Exact coherent approval forgery: rejected with self-validation, a forged policy, and the real
  lease-backed authorization-aware cache; the original approval remains valid.
- Canonical `kinocut`/`mcp_video` compatibility import: pass.
- Ruff, formatting, diff, leak, artifact, sidecar-boundary, readiness, and public-surface gates:
  pass, with only the expected pre-push no-upstream readiness warning.
- Changed-module ceiling: maximum **673 LOC**; no changed function exceeds **80 lines**.
- Independent final verdict: **APPROVE / CLEAR**.

All implementation, remediation, and independent-review estimates recorded actuals through the
latest installed Epoch runtime.

## Deliberate boundaries and next dependency

- S3 defines provider and cache trust contracts; concrete voice, post/spatial, ambience, and final
  mix invocation belongs to S5-S9.
- Public aggregate Python exports, CLI, MCP, WF host binding, and legacy compatibility remain the
  serialized S12/S13 joins.
- The HMAC approval proof is a trusted in-process bearer capability, not hostile-code process
  isolation.
- No version, release file, tag, public tool registry, CLI command, deployment, or announcement
  changed.

The next parallel-ready leaves are **S5 — base voice**, **S7 — post/spatial**, and **S8 — ambience**.
Their dependent joins remain S6/S10 after S5, S9 after S5+S7+S8, and S11 after S4+S7+S9.

## Release stop

Continue from S5, S7, and S8 after this checkpoint merges. Stop before any version bump, tag,
upload, deployment, release, or announcement and request explicit authority.
