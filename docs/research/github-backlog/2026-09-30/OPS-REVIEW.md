# GitHub ops/product issue findings — 2026-09-30

Read-only external triage plus local documentation clarification. No company systems, credentials, workflow activation, deploys, issue states, or publishing changed. Durable board: docs/status/2026-09-30-ops-disposition.md. Local package metadata: 1.15.3 candidate; maintained published status: 1.15.2. Issue-body assertions were not treated as current live proof.

## [#476](https://github.com/KyaniteLabs/kinocut/issues/476), gated-surface wayfinder

**Disposition:** Local map supplied; retain external gates

This board assigns each child a disposition. Projectstore, watching, and multiplier planning already exist; [phase checkpoints](../../../status/PHASE_CHECKPOINTS.md) describe their scoped exits. Neither backend execution nor product listening approval follows from those phase exits.

## [#477](https://github.com/KyaniteLabs/kinocut/issues/477), MCPB product direction

**Disposition:** Staged direction embodied locally; native remains separate

[MCPB.md](../../../MCPB.md) selects an unsigned launcher using an existing installed Python environment and calls its access model `user-configured-local-access`. Native bundles have separate [runtime supply-chain requirements](../../../MCPB_SUPPLY_CHAIN.md). A native-bundle decision does not block staged artifact validation; it does not authorize staged publication either.

## [#479](https://github.com/KyaniteLabs/kinocut/issues/479), site version and TLS

**Disposition:** Keep external deployment verification pending

The maintained status board records source corrections and pending production rendering. The separate site repository and Netlify deployment are outside this checkout. Site owner must deploy the intended source and capture production version/count, HTTPS, and `llms.txt` evidence. A source edit alone cannot close this gate.

## [#481](https://github.com/KyaniteLabs/kinocut/issues/481), sound S14/product scope

**Disposition:** Keep full-episode claim gated; accept bounded fixture scope

The [sound checkpoint](../../../status/PHASE_CHECKPOINTS.md#sound-program-not-a-phase-14-exit-residual-portfolio) distinguishes synthetic fixture plumbing from product completion. The [August rerun](../../../evidence/2026-08-12-sound-s14-live-rerun.json) records Apple hardware and an unavailable x86 host. `kinocut/sound_joins/benchmark.py` synthesizes tones: hardware provenance alone does not turn this into a real episode or a human listening pass. Claim owner must supply representative end-to-end episode/listening evidence or explicitly retain the narrower scope.

## [#482](https://github.com/KyaniteLabs/kinocut/issues/482), still-plate/paid adapters

**Disposition:** Ship documented deterministic features; keep paid execution gated

[STILL_PLATES.md](../../../STILL_PLATES.md) documents shipped Pillow operations, mean-RGB establishment matching, and cohesion checks. Image-edit intent is audit metadata and does not drive pixels. Paid requests return `paid_edit_backend_unavailable`; do not remove useful deterministic features because a paid adapter is absent. A future execution adapter needs an approved provider, explicit capability semantics, and spend controls. No credentials were provisioned.

## [#483](https://github.com/KyaniteLabs/kinocut/issues/483), directories/launch

**Disposition:** Preparation exists; retain external approval and publication

[HUMAN_GATES.md](../../../HUMAN_GATES.md), [directory ledger](../../../DIRECTORY_REBRAND_STATUS.md), and [launch drafts](../../../status/LAUNCH_MOMENTS.md) track outcomes. Awesome MCP merged is recorded evidence; other reviews and post approval remain owner actions. Neither a draft nor an open submission is a published result.

## [#484](https://github.com/KyaniteLabs/kinocut/issues/484), operator/company actions

**Disposition:** Operator prerequisite; no product-runtime change required

Disabled hourly-job cleanup, organization membership, and company-message outcome confirmation require the relevant operator/admin. This repository cannot establish their current external state, and those actions do not justify new runtime gates or use of company credentials.

## [#485](https://github.com/KyaniteLabs/kinocut/issues/485), staged MCPB non-decision gates

**Disposition:** Implementation supplied; exact-artifact evidence still required

`.github/workflows/mcpb.yml` already defines locked official validation, installed clean-runtime jobs for macOS/Linux/Windows, process-tree cleanup, absent/present optional-dependency checks, and an aggregate receipt. Run results must bind the candidate source SHA, wheel, and archive digest. [MCPB.md](../../../MCPB.md) also retains actual desktop import and publication review; hosted runtime CI is not a desktop-import receipt.

## [#487](https://github.com/KyaniteLabs/kinocut/issues/487), TEK Phase 0 exit receipt

**Disposition:** Missing retrospective receipt remains explicit

The Phase 0 checkpoint below is pending verification. Later phases shipping does not prove the original distribution exit was recorded. Capture per-criterion package/shim, renamed repository, registry, clean installed CLI, and production site/docs evidence with dates and source identities, then record the owner's exit decision. This review cannot reconstruct a historical GO from issue assertions.

## [#488](https://github.com/KyaniteLabs/kinocut/issues/488), mirror divergence

**Disposition:** Preserve both histories; reconcile before activation

The issue's later review identifies divergence, superseding its earlier token-missing diagnosis. Current [human gates](../../../HUMAN_GATES.md) require reviewed reconciliation and protected fast-forward downstream sync. Do not force-push, discard downstream-only commits, or provision the obsolete `MIRROR_GITHUB_TOKEN` setup. Remote graph/evidence and any reconciliation PR belong to the active integration review.

## [#499](https://github.com/KyaniteLabs/kinocut/issues/499), forge policy

**Disposition:** GitHub-primary policy implemented locally; activation pending

[Directory status](../../../DIRECTORY_STATUS.md) and `.github/workflows/sync-forgejo.yml` describe GitHub source/contribution/CI authority and Forgejo downstream. Both sync jobs require the activation variable. Restricted credentials, explicit inactive/active readback, protected reconciliation, and downstream exact-head CI remain operator evidence in [HUMAN_GATES.md](../../../HUMAN_GATES.md). Local workflow code is not proof of live activation.

## [#502](https://github.com/KyaniteLabs/kinocut/issues/502), product handoff

**Disposition:** Refresh handoff evidence; role authority remains external

The old handoff's Revideo and contribution-credit loops are already addressed in [CHANGELOG.md](../../../../CHANGELOG.md): four guarded Revideo operations, 201 MCP/173 CLI, and WohaibHasan credits. Remaining distribution loops are separated above. This board does not appoint a PM, inherit company-chat authority, or approve a release.

## Local changes and verification

- Added docs/PROJECTSTORE_LIFECYCLE.md with recorded CAS recovery/backups and truthful cancellation/reconciliation semantics.
- Updated docs/AI_VIDEO_CONTRACTS.md, docs/security/PROJECTSTORE_THREAT_MODEL.md, and ADR 0008; preserved historical decisions.
- Added dated ops disposition board and explicit pending Phase 0 row in PHASE_CHECKPOINTS; corrected obsolete First10/Renovate rows against HUMAN_GATES.
- Added current-status amendment to approved TEK plan preserving July baseline and original decisions while preventing stale gates from misrepresenting shipped implementations.
- Product agent independently corrected NOW stale Renovate row and linked lifecycle documentation.
- Local Markdown links and lifecycle fenced Python snippets validated; git diff --check passes. No new runtime edits or runtime tests in this documentation pass.

## Remaining evidence limitations

- The staged MCPB workflow implements official validator and three-host installed-runtime checks, but this review does not establish that the current candidate exact digest passed hosted jobs or desktop import.
- The S14 Apple hardware receipt is for synthetic fixture plumbing; neither it nor class naming in July receipts proves representative episode quality or listening approval.
- No Phase 0 GO was fabricated: clean published install, registry, production site/docs, shim resolution and dated owner exit decision still require referenced evidence.
- Mirror history reconciliation and actual inactive/active setting readback are root integration/operator work; token-missing historical diagnosis should not trigger obsolete token provisioning.
- External issue closure remains separate from underlying local work being addressed.

## Public read-only followup

- #479: HTTPS home and llms requests failed CONNECT/proxy403; no deployed-content or origin TLS verdict.
- #488/#499: public Forgejo refs with credential.helper disabled failed CONNECT403; remote head remains unverified.
- #485: public GitHub run https://github.com/KyaniteLabs/kinocut/actions/runs/36167328576 reports Success for a820bd42205e43ca81eebc435e8529b2d0d42fcc, triggered Sep25 17:28 UTC. Three clean-runtime jobs, build/official validation, optional callability, aggregate evidence, and six artifacts shown. This establishes a historical exact-source workflow success, superseding the earlier unknown-results wording. Artifact contents/archive digests and actual desktop import were not retrieved or independently verified; these checks do not cover current uncommitted changes.
