# Kinocut now

GitHub backlog review and local fixes: [September 30 report](../research/github-backlog/2026-09-30/REPORT.md).

**Published:** 1.15.3 · **201 MCP / 173 CLI** · 2026-09-25 · `docs/public_claims.json`

**Tip (`master`):** 1.15.3 · **201 MCP / 173 CLI** (same registered surface as published 1.15.3; current local changes remain Unreleased). Pip history in one line: 1.14.1 = 360 dual-cam + lazy import; 1.15.0 = honest diagnostics + first-class Windows; 1.15.1 (2026-08-31) = registry ownership (shim 1.6.12, #469) + object-matte streaming decode/scratch guards (#412/#414, installable as `kinocut[object-matte]`); 1.15.2 (2026-09-24) = guarded Revideo operations + verified stereo mastering + adversarial hardening, surface 201 MCP / 173 CLI.

**Product pipeline:** Phase 1–4 + Track E **GO**.

**Default agent path:** doctor/info → `video_intent` (`goal=` compiles a cutfile; a 360/desk/table goal also proposes a `360_assembly_plan`) → review → render → QC → human review. Operator guide: [360_ASSEMBLY.md](../360_ASSEMBLY.md).

**Human residuals:** directories #88 and launch #90. GitHub Dependabot is canonical; the old Forgejo Renovate-token gate is superseded and those tokens must not be provisioned for Kinocut ([HUMAN_GATES](../HUMAN_GATES.md)). First-10 **closed**. MCPB unsigned is the selected `user-configured-local-access` path; its exact-digest hosted and desktop-install gates remain distinct. Real X4 dogfood is optional; synthetic 2:1 fixtures cover the compiler.

**Provider verification (2026-09-30):** PyPI and npm report **1.15.3**; live kinocut.dev JSON-LD and llms.txt also report **1.15.3**. GitHub `releases/latest` reports **1.15.0**. The MCP Registry request returned **403**, so its current version is unverified. These checks do not prove every provider is aligned or every site page is visually correct.

**Desk residual:** Colima is the operator M4 Mac, not Mini. Do not restart `forgejo-runner` mid-job (exact 80s fail). Perf-committee reports are inspect receipts only ([README](perf-committee/README.md)). Receipt: [2026-08-19-ops-closeout.md](2026-08-19-ops-closeout.md).

**Perf receipt:** cheap CLI + import timings in [golden-path-timings.md](golden-path-timings.md) — baseline only, not an optimized claim.

**Current development review:** [2026-09-30 ops disposition](2026-09-30-ops-disposition.md) records which old operational gates are superseded and which still require owner evidence. Local runtime adaptations are Unreleased; published identity remains above.

**Living authority:** [ops closeout 2026-08-19](2026-08-19-ops-closeout.md) · [residual matrix](2026-08-12-residual-maturity-matrix.md) · [HUMAN_GATES](../HUMAN_GATES.md). S+ excellence PRD is local-only (`.omx/plans/`, gitignored).
