# Kinocut now

GitHub backlog review and local fixes: [September 30 report](../research/github-backlog/2026-09-30/REPORT.md).

**Latest audit delivery:** [PR #588](https://github.com/KyaniteLabs/kinocut/pull/588)
fixes the18 findings in the [debt closure ledger](../research/DEBT_CLOSURE.md).
Selected source passed8,297 tests with189skips; exact2d903f7 passed all13checks
including native Linux/macOS/Windows and bound installed-runtime readiness.
See that PR for final documentation-head checks and merge status.
Paid accuracy, representative listening, human desktop review and external owner
gates remain explicitly separate. Maintenance [PR #596](https://github.com/KyaniteLabs/kinocut/pull/596)
merged at `9727d465d698950f4054f868806a32a78876af8f`; tag and GitHub release
`v1.16.1` target that commit. Implementation QA passed 8,973 tests with 193 skips,
all thirteen exact-head checks passed, and the installed-artifact adversarial checks passed twice.
PyPI and npm publicly report 1.16.1; shim 1.6.16 pins that version. The initial
publication gate read MCP Registry 1.16.1 but failed while npm still showed 1.16.0.
Later npm reads confirmed 1.16.1; local MCP Registry rechecks timed out.

**Previous merged audit:** [PR #587](https://github.com/KyaniteLabs/kinocut/pull/587)
landed at `3db9ba9f9cad590f4c018b76091ee3c27e7106fd`. Its tested source passed
8,013 tests with 189 skips and thirteen exact-head checks. Further resource,
architecture and acceptance work is tracked in the
[debt closure ledger](../research/DEBT_CLOSURE.md); separate checkpoint results there are
separate from the merged audit's evidence.

**Published:** 1.16.1 · **203 MCP / 177 CLI** · 2026-10-05 · `docs/public_claims.json`

**Development candidate:** 1.16.1 · **203 MCP / 177 CLI** (matches the published maintenance package). Pip history in one line: 1.14.1 = 360 dual-cam + lazy import; 1.15.0 = honest diagnostics + first-class Windows; 1.15.1 (2026-08-31) = registry ownership (shim 1.6.12, #469) + object-matte streaming decode/scratch guards (#412/#414, installable as `kinocut[object-matte]`); 1.15.2 (2026-09-24) = guarded Revideo operations + verified stereo mastering + adversarial hardening, surface 201 MCP / 173 CLI.

**Historical product checkpoint:** Phase 1–4 + Track E **GO**. Current sound
support covers deterministic processing and measured policy/resource controls;
full-episode and listening acceptance require separate evidence. See the
[supported-scope amendment](../research/debt-closure-operations.md).

**Historical release provider verification (2026-10-02):** PyPI/npm/GitHub latest release/canonical MCP Registry reported 1.16.0; shim 1.6.15 forwarded canonical extras and pinned 1.16.0. The live site was verified at 1.16.0 on 2026-10-05, superseding the older site-update and DNS blockers. Website 1.16.1 source is prepared; deployment, rendered acceptance and fleet rollout remain open. Forgejo product synchronization is disabled; canonical website source remains Forgejo.

**Default agent path:** doctor/info → `video_intent` (`goal=` compiles a cutfile; a 360/desk/table goal also proposes a `360_assembly_plan`) → review → render → QC → human review. Operator guide: [360_ASSEMBLY.md](../360_ASSEMBLY.md).

**Human residuals:** directories #88 and launch #90. GitHub Dependabot is canonical; the old Forgejo Renovate-token gate is superseded and those tokens must not be provisioned for Kinocut ([HUMAN_GATES](../HUMAN_GATES.md)). First-10 **closed**. MCPB unsigned is the selected `user-configured-local-access` path; its exact-digest hosted and desktop-install gates remain distinct. Real X4 dogfood is optional; synthetic 2:1 fixtures cover the compiler.

**Historical provider verification (2026-09-30):** PyPI and npm report **1.15.3**; live kinocut.dev JSON-LD and llms.txt also report **1.15.3**. GitHub `releases/latest` reports **1.15.0**. The MCP Registry request returned **403**, so its current version is unverified. These checks do not prove every provider is aligned or every site page is visually correct.

**Historical site verification (2026-10-01, 22:58 UTC):** certificate-verified homepage
and llms requests returned 200 for the disclosed verification client and confirmed
the published 1.15.3 stamp. [Response digests and client limits](../proofs/2026-10-01-published-site-verification.md)
supersede the earlier blocked observations for issue #479. Candidate 1.16.0,
other pages/providers, visual acceptance and the Phase-0 exit are not accepted
by this check.

**Desk residual:** Colima is the operator M4 Mac, not Mini. Do not restart `forgejo-runner` mid-job (exact 80s fail). Perf-committee reports are inspect receipts only ([README](perf-committee/README.md)). Receipt: [2026-08-19-ops-closeout.md](2026-08-19-ops-closeout.md).

**Perf receipt:** cheap CLI + import timings in [golden-path-timings.md](golden-path-timings.md) — baseline only, not an optimized claim.

**Current development review:** [2026-09-30 ops disposition](2026-09-30-ops-disposition.md) records which old operational gates are superseded and which still require owner evidence. Local runtime adaptations are Unreleased; published identity remains above.

**Living authority:** [ops closeout 2026-08-19](2026-08-19-ops-closeout.md) · [residual matrix](2026-08-12-residual-maturity-matrix.md) · [HUMAN_GATES](../HUMAN_GATES.md). S+ excellence PRD is local-only (`.omx/plans/`, gitignored).
