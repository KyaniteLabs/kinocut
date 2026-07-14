# Sound S2/S4 integration checkpoint

**Snapshot date:** 2026-07-13

> **Historical pre-release snapshot:** This checkpoint predates the published 1.8.0
> release and is retained as implementation evidence, not current release guidance.

**Reviewed implementation tip:** 006a50b

**State:** integrated and verified in the recorded local validation environment; independently approved; unreleased at the snapshot date

## Executive summary

This checkpoint closes the next two dependency-critical kinocut_sound leaves without crossing the
public-adapter or release boundaries:

- **S2 — authorization, provenance, and privacy runtime**; and
- **S4 — generic/WF script parsing plus deterministic episode planning against typed fakes.**

S1 was already present. S2 and S4 were implemented in isolated worktrees, hardened through
observed RED-to-GREEN hostile tests, independently reviewed to APPROVE/CLEAR, then serialized into
one integration branch. S3 is now the next blocking leaf; S5 cannot start until S3 is complete.

This is an implementation checkpoint, not a release candidate. It authorizes no version bump,
tag, package upload, registry submission, deployment, release creation, or announcement.

## S2 authorization runtime

The new runtime provides:

- append-only, privacy-safe ledger events with hashed complete authorization context;
- fail-closed grant registration, issue/expiry liveness, scope, project, character, provider,
  territory, blend, and cloud-egress enforcement;
- compare-before-replace transitions and generation leases;
- WAIT/CANCEL revocation behavior, pre-commit reauthorization, and lifecycle locking;
- transitive derivative lineage, quarantine/deletion outcomes, and delete precedence;
- authorization checks for generation, cache reuse, assembly, and export; and
- bounded custom errors without subject identity, biometric material, raw context, host paths, or
  credentials in serialized events.

The exact reviewed author tip was ad6918c. The independently reviewed commits were replayed onto
the integration branch as 1c37fff through 2932f71.

## S4 parser and pure episode planner

The new standalone planning path provides:

- strict generic and WF input parsing for dialogue, confessionals, narration, action, voiceover,
  chapter cards, and beats;
- privacy-safe hashed text records and deterministic canonical identities;
- exact actor, scene, line, beat, event, cue, and chapter-card referential integrity;
- source-order cue spotting, pacing, designed silence, routing intent, and Foley cue contracts;
- exact clip-set and timeline/artifact integrity with all-or-nothing cancellation;
- constructed-model and hostile runtime-type revalidation at public Python boundaries; and
- enforced actor/scene/line/beat/turn/event/text resource ceilings, including bounded generators
  and caller-controlled mappings counted by their actual yielded entries;
- privacy-safe custom-error normalization for unexpected iterable and mapping traversal failures.

The final independently reviewed author tip was 1e44aed. Its reviewed sequence, including the
controller-owned limit/export joins and two adversarial boundary-remediation rounds, was replayed
onto integration as 89bc196 through 006a50b.

## Verification receipt

- All kinocut_sound tests on the combined tip: **237 passed**.
- Serialized full repository suite on 006a50b: **3624 passed, 18 skipped, 8 warnings in 611.90s**.
- Canonical compatibility import: pass.
- Ruff on kinocut_sound and its tests: pass.
- Git diff check: pass.
- Focused leak/credential scans: pass.
- S2 independent review: **APPROVE / ARCHITECTURE CLEAR**.
- S4 independent review: **APPROVE / CLEAR**.
- Module limits: authorization.py 783 LOC, script_parser.py 795 LOC, episode_assembly.py 437 LOC,
  and _input_bounds.py 80 LOC; no changed function exceeds 80 lines.

All leaf and review-remediation estimates recorded actuals through the latest installed Epoch
runtime. Key feedback receipts include:

- S2 author/hardening: d26477d2, a8a3b180, cfbdba28, 775eaaa9;
- S4 author/hardening: 928e1973, 97f45695, b162ffec, f9b8614e, da6c9971, e1a73a93,
  3565440e, 85120e20, and 2db63917; and
- controller limit/export joins: 2a6bd734, 915973b4, and 686408d3.

## Deliberate boundaries and next dependency

- S2 handles authorization records and derived lineage, not biometric-byte storage or voice
  generation.
- S4 produces privacy-safe plans against typed fakes; it does not render speech, ambience, or a
  final mix.
- Public Python aggregate exports, CLI, MCP, WF host binding, and legacy compatibility remain the
  later serialized S12/S13 joins.
- No release surface changed.

The highest-leverage next leaf is **S3 — static registry, config, provider policy, full render
fingerprint, and authorization-aware cache**. After S3, S5 voice, S7 post/spatial, and S8 ambience
can proceed according to their dependency gates. The protected-timeline kernel remains separately
human-gated.

## Release stop

Continue implementation from S3 after this checkpoint merges. Stop before any version bump, tag,
upload, deployment, release, or announcement and request explicit authority.
