# Pending distribution and product decisions — checkout evidence

**Reviewed:** 2026-09-30. This board reconciles the open GitHub issues with the
current checkout. It records local preparation and remaining evidence; it is not
a deployment receipt, publication approval, company role appointment, or proof
that a remote workflow has run. Historical issue bodies are inputs, not current
execution authority. Repository package version is 1.15.3; the maintained
[current status](NOW.md) distinguishes that candidate from published 1.15.2.

| Issue | Disposition | Evidence and next concrete requirement |
| --- | --- | --- |
| [#476](https://github.com/KyaniteLabs/kinocut/issues/476), gated-surface wayfinder | Local map supplied; retain external gates | This board assigns each child a disposition. Projectstore, watching, and multiplier planning already exist; [phase checkpoints](PHASE_CHECKPOINTS.md) describe their scoped exits. Neither backend execution nor product listening approval follows from those phase exits. |
| [#477](https://github.com/KyaniteLabs/kinocut/issues/477), MCPB product direction | Staged direction embodied locally; native remains separate | [MCPB.md](../MCPB.md) selects an unsigned launcher using an existing installed Python environment and calls its access model `user-configured-local-access`. Native bundles have separate [runtime supply-chain requirements](../MCPB_SUPPLY_CHAIN.md). A native-bundle decision does not block staged artifact validation; it does not authorize staged publication either. |
| [#479](https://github.com/KyaniteLabs/kinocut/issues/479), site version and TLS | Keep external deployment verification pending | The maintained status board records source corrections and pending production rendering. Read-only HTTPS requests to `https://kinocut.dev/` and `/llms.txt` on this review date failed with CONNECT/proxy HTTP 403, so this review establishes neither production content nor site TLS health. The separate site repository and Netlify deployment are outside this checkout. Site owner must deploy the intended source and capture production version/count, HTTPS, and `llms.txt` evidence. A source edit alone cannot close this gate. |
| [#481](https://github.com/KyaniteLabs/kinocut/issues/481), sound S14/product scope | Keep full-episode claim gated; accept bounded fixture scope | The [sound checkpoint](PHASE_CHECKPOINTS.md#sound-program-not-a-phase-14-exit-residual-portfolio) distinguishes synthetic fixture plumbing from product completion. The [August rerun](../evidence/2026-08-12-sound-s14-live-rerun.json) records Apple hardware and an unavailable x86 host. `kinocut/sound_joins/benchmark.py` synthesizes tones: hardware provenance alone does not turn this into a real episode or a human listening pass. Claim owner must supply representative end-to-end episode/listening evidence or explicitly retain the narrower scope. |
| [#482](https://github.com/KyaniteLabs/kinocut/issues/482), still-plate/paid adapters | Ship documented deterministic features; keep paid execution gated | [STILL_PLATES.md](../STILL_PLATES.md) documents shipped Pillow operations, mean-RGB establishment matching, and cohesion checks. Image-edit intent is audit metadata and does not drive pixels. Paid requests return `paid_edit_backend_unavailable`; do not remove useful deterministic features because a paid adapter is absent. A future execution adapter needs an approved provider, explicit capability semantics, and spend controls. No credentials were provisioned. |
| [#483](https://github.com/KyaniteLabs/kinocut/issues/483), directories/launch | Preparation exists; retain external approval and publication | [HUMAN_GATES.md](../HUMAN_GATES.md), [directory ledger](../DIRECTORY_REBRAND_STATUS.md), and [launch drafts](LAUNCH_MOMENTS.md) track outcomes. Awesome MCP merged is recorded evidence; other reviews and post approval remain owner actions. Neither a draft nor an open submission is a published result. |
| [#484](https://github.com/KyaniteLabs/kinocut/issues/484), operator/company actions | Operator prerequisite; no product-runtime change required | Disabled hourly-job cleanup, organization membership, and company-message outcome confirmation require the relevant operator/admin. This repository cannot establish their current external state, and those actions do not justify new runtime gates or use of company credentials. |
| [#485](https://github.com/KyaniteLabs/kinocut/issues/485), staged MCPB non-decision gates | Implemented CI has a public successful run; archive/desktop evidence remains scoped | `.github/workflows/mcpb.yml` already defines locked official validation, installed clean-runtime jobs for macOS/Linux/Windows, process-tree cleanup, absent/present optional-dependency checks, and an aggregate receipt. Public [run 36167328576](https://github.com/KyaniteLabs/kinocut/actions/runs/36167328576) reports Success for `a820bd42205e43ca81eebc435e8529b2d0d42fcc` on 2026-09-25, including three clean-runtime jobs, optional callability, and aggregate evidence. Its page lists six artifacts including an aggregate receipt; their displayed artifact-storage digests do not substitute for inspecting the contained candidate wheel/archive digest receipt. This predates the uncommitted improvements in this review. [MCPB.md](../MCPB.md) also retains actual desktop import and publication review; hosted runtime CI is not a desktop-import receipt. |
| [#487](https://github.com/KyaniteLabs/kinocut/issues/487), TEK Phase 0 exit receipt | Missing retrospective receipt remains explicit | The Phase 0 checkpoint below is pending verification. Later phases shipping does not prove the original distribution exit was recorded. Capture per-criterion package/shim, renamed repository, registry, clean installed CLI, and production site/docs evidence with dates and source identities, then record the owner's exit decision. This review cannot reconstruct a historical GO from issue assertions. |
| [#488](https://github.com/KyaniteLabs/kinocut/issues/488), mirror divergence | Preserve both histories; reconcile before activation | The issue's later review identifies divergence, superseding its earlier token-missing diagnosis. Current [human gates](../HUMAN_GATES.md) require reviewed reconciliation and protected fast-forward downstream sync. Do not force-push, discard downstream-only commits, or provision the obsolete `MIRROR_GITHUB_TOKEN` setup. A credential-disabled public `git ls-remote` attempt against Forgejo failed CONNECT HTTP 403 on this review date; no current Forgejo head was established. Remote graph/evidence and any reconciliation PR belong to the active integration review. |
| [#499](https://github.com/KyaniteLabs/kinocut/issues/499), forge policy | GitHub-primary policy implemented locally; activation pending | [Directory status](../DIRECTORY_STATUS.md) and `.github/workflows/sync-forgejo.yml` describe GitHub source/contribution/CI authority and Forgejo downstream. Both sync jobs require the activation variable. Restricted credentials, explicit inactive/active readback, protected reconciliation, and downstream exact-head CI remain operator evidence in [HUMAN_GATES.md](../HUMAN_GATES.md). Local workflow code is not proof of live activation. |
| [#502](https://github.com/KyaniteLabs/kinocut/issues/502), product handoff | Refresh handoff evidence; role authority remains external | The old handoff's Revideo and contribution-credit loops are already addressed in [CHANGELOG.md](../../CHANGELOG.md): four guarded Revideo operations, 201 MCP/173 CLI, and WohaibHasan credits. Remaining distribution loops are separated above. This board does not appoint a PM, inherit company-chat authority, or approve a release. |

## Phase 0 verification record still needed

The approved [trusted-execution plan](../plans/2026-07-09-kinocut-trusted-execution-layer.md#phase-0--kinocut-rename-cutover-identity-pivot)
defines the rename exit. A completed receipt should preserve the actual historical
release identities or clearly label a new verification, rather than silently
substitute today's candidate version.

| Criterion | Available checkout evidence | Unresolved receipt requirement |
| --- | --- | --- |
| Clean installed `kino` CLI | Package metadata, compatibility tests, installed-runtime CI preparation | Identify the tested published artifact and attach clean-install execution evidence. |
| Renamed source repository | Canonical GitHub links and downstream policy | Capture the intended remote identity and reconciliation status; a local remote name is insufficient. |
| Registry listing | `server.json`, directory ledger, published-claims checks | Attach the registry response for the intended published release, not only its checked-in descriptor. |
| Site/docs identity and counts | Maintained claims and site correction notes | Production deployment, HTTPS, rendered identity/counts, and `llms.txt` verification from the site owner. |
| Compatibility shim resolves | Distribution metadata and compatibility tests | Attach published shim dependency and clean-install resolution evidence. |

Until those references and the explicit exit decision are recorded, Phase 0 is
**pending retrospective verification**, while the later implementation checkpoints
retain their own scoped historical evidence. No issue labels, remote settings,
deployments, directory submissions, or publications were changed by this review.

## Public read-only checks (2026-09-30)

GitHub workflow listing and run details returned HTTPS 200 with certificate
verification enabled. The run page records the source commit and successful
workflow status above; the raw downloaded pages are investigation evidence, not
a newly generated publication receipt. Artifact contents were not retrieved.
Site and Forgejo requests failed at the network CONNECT proxy, so their HTTP 403
errors must not be presented as failures of the deployed product itself. No
credentials, settings, or remote branches were changed.
