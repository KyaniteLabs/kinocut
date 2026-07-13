# Kinocut sound program strategic handoff

**Date:** 2026-07-13

**Audience:** follow-on implementation agents and controller

**Release state:** unreleased; no release action is authorized

## BLUF

S1-S4 are implemented. S3 is independently approved at `3d881113` with the full repository suite
green. Merge the S3 checkpoint PR, then execute S5, S7, and S8 as disjoint leaves. Do not start a
public CLI/MCP/host join before S12. Do not release, publish, deploy, tag, bump a version, or announce.

Authoritative sources:

- [sound design](../superpowers/specs/2026-07-11-kinocut-sound-sonic-world-design.md)
- [sound plan index](../superpowers/plans/2026-07-12-kinocut-sound-plan-index.md)
- [S2/S4 checkpoint](2026-07-13-sound-s2-s4-integration-checkpoint.md)
- [S3 checkpoint](2026-07-13-sound-s3-integration-checkpoint.md)
- [all-open-loops manifest](../plans/2026-07-12-kinocut-open-loops-audit-manifest.md)

## Proven state

- S1: backend-neutral plan, timeline, routing, delivery, consent, receipt, capability, format, line,
  and fingerprint contracts.
- S2: fail-closed authorization, leases, revocation, lineage, privacy, cloud/blend scope, quarantine,
  and deletion.
- S3: sealed registry, versioned presets/config, exact provider policy, complete fingerprint, and
  authorization-aware cache.
- S4: strict generic/WF parsing and deterministic pure episode planning against typed fakes.
- Final S3 evidence: 53 focused, 290 sound, 22 architecture, and 3677 full-suite tests passed;
  independent verdict APPROVE/CLEAR.
- S5-S15 remain open. Existing Kinocut audio helpers are downstream composition targets, not proof
  that these sound leaves or public joins are complete.

## Critical-path DAG

```text
Wave A: S5 base voice || S7 post/spatial || S8 ambience
Wave B: S5 -> (S6 cloning/blending || S10 voice consistency)
Wave C: S4 + S5 + S7 + S8 -> S9 assembly/mix/stems
Wave D: S4 + S7 + S9 -> S11 QA/metadata
Wave E: implemented S4-S11 -> S12 public parity -> S13 host joins
Wave F: S5-S13 -> S14 benchmark -> S15 final acceptance and release stop
```

S9 clone-derived fixtures additionally wait for S6. S10 consent-derived cases wait for S6. S13
also waits for the external G007/D41-D42 owner wave and its host review/learning/benchmark
contracts. S14 requires both approved Apple-silicon and x86 Linux benchmark classes; an unavailable
class is `external_host_unavailable`, never a pass.

## Recommended ownership boundaries

Workers own only their leaf modules and tests. The controller alone owns shared exports,
`defaults.py`, `limits.py`, `validation.py`, public manifests, CLI/MCP registration, and status
ledgers.

| Leaf | Worker-owned implementation area | Required proof |
| --- | --- | --- |
| S5 | new `kinocut_sound/voice/` package: roster, local adapter, pronunciation/prosody, deterministic batch | 15+ roster, typed-plan batch, deterministic output identity, absent-provider behavior |
| S7 | new `kinocut_sound/post/` package: denoise, de-ess/EQ/dynamics, convolution/spatial, loudness/TP, overrides | fixed audio fixtures, numeric acceptance, optional-neural fail-soft, deterministic batch |
| S8 | new `kinocut_sound/world/` package: licensed catalog, audition, layers, loops, location/deck presets, Foley resolver | license/authorization lineage, seamless-loop proof, S4 cue-id integrity, fake D41 only |
| S6 | `kinocut_sound/voice/` clone/blend extension after S5 | per-source grants, local/cloud policy, generation lease, lineage, revocation race |
| S10 | new `kinocut_sound/voice_consistency/` package | versioned profiles, identity/style metrics, drift/distinctiveness, fake D42 regeneration |
| S9 | new `kinocut_sound/mix/` package | placement, crossfades, silence, buses, automation, ducking, latency, stems, tail/duration proof |
| S11 | new `kinocut_sound/qa/` package | loudness/TP/LRA, ASR, artifact/spectral/sync/stem checks, chapters/ISRC, season rollup |
| S12 | controller-serialized thin Python/CLI/MCP adapters only | flat/namespaced parity, non-TTY JSON, privacy/error parity, capability discovery |
| S13 | controller-serialized Kinocut/WF/legacy host joins | D41/D42 contracts, compatibility, review/learning/benchmark owner receipts |
| S14 | scheduler and versioned benchmark fixtures | bounded pool, cancel/resume, resource ceilings, cold/warm runs on both required classes |
| S15 | receipts and adversarial acceptance only | authorization/revocation, determinism, privacy/leak, full suite, independent reviews, STOP |

If an implementation grows toward 800 lines, split the package before review. No function may exceed
80 lines. Reuse existing canonical bounds, errors, fingerprints, registry, provider policy, cache,
authorization, and timeline utilities; do not clone them inside a leaf.

## Per-leaf execution recipe

1. Verify live Niko identity, clean `master`, canonical Forgejo remote, and no stale worktree.
2. Run the latest installed Epoch estimate and retain its feedback token.
3. Branch from current `master` with a `codex/` name. One leaf equals one change unit.
4. Write focused RED tests from the design acceptance rows before production code.
5. Keep hostile input, privacy, cancellation, authorization, determinism, and resource ceilings in
   the first test set, not a later cleanup.
6. Run focused tests, all `test_kinocut_sound_*.py`, architecture/centralization tests, Ruff,
   compatibility import, diff, leak/artifact, module/function, and sidecar-boundary gates.
7. Run `python3 -m pytest tests/ -x -q --tb=short` under the shared full-suite lock before commit.
8. Commit with noreply metadata and record Epoch actual.
9. Obtain independent read-only APPROVE/CLEAR on the exact tip; remediate every reproduced blocker
   RED-first.
10. Controller updates the plan/status receipt, runs the public leak audit, pushes, opens a protected
    Forgejo PR, waits required CI, merges, fast-forwards `master`, and deletes branch/worktree/ref.
11. Stop at the next dependency boundary. Never smuggle S12/S13 public-surface work into a leaf.

## Review checklist for less-capable agents

A leaf is not complete because imports work or mocks pass. Review must prove:

- every design acceptance row assigned to the leaf has an executable test;
- constructed Pydantic objects, lying mappings, generators over limits, and hostile properties fail
  with bounded custom errors and no private marker/path leakage;
- cloud/provider use is exact-route authorized and local-first behavior never constructs cloud;
- consent-derived bytes have live grants, generation leases, transitive lineage, and revocation
  behavior;
- cache keys bind complete fingerprints and cache hits reauthorize exact current policy;
- deterministic claims compare complete normalized inputs, toolchains, policy, and outputs;
- optional capability absence is explicit and does not silently weaken required acceptance;
- artifact hashes, durations, sample rates, channels, loudness, true peak, stems, and tails are
  checked where relevant; and
- no release surface or unrelated project file changed.

## Strategic stop conditions

Pause and escalate rather than guessing when:

- S13 external owner receipts are absent;
- a required S14 hardware class is unavailable;
- a change would touch CLI/MCP/public manifests before S12;
- a worker needs shared defaults/limits/exports while another leaf is active;
- independent review reproduces an authorization, privacy, determinism, or artifact-integrity bypass;
- the protected-timeline kernel gate is implicated; or
- any release, publish, deploy, tag, version, or announcement action would be next.

## Next action

After the S3 PR merges and cleanup is proven, dispatch exactly three isolated authors for S5, S7,
and S8. Give each the relevant design rows, the ownership table above, a RED-first requirement, and
an explicit ban on shared/public files. The controller should prepare shared joins only after all
three exact tips are independently clear.
