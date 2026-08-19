# Kinocut now

**Published:** 1.15.0 · **196 MCP / 167 CLI** · `docs/public_claims.json`

**Tip (`master`):** 1.15.0 (same counts). 360 dual-cam assembly and PEP 562 lazy `import kinocut` shipped in pip **1.14.1**. Honest diagnostics (`--mcp` import errors, doctor `mcp-server-import`) and first-class Windows support are in pip **1.15.0**. Dual-host matched at `5b1936e` on 2026-08-19 (Forgejo = GitHub); combined status on that SHA was success.

**Product pipeline:** Phase 1–4 + Track E **GO**.

**Default agent path:** doctor/info → `video_intent` (`goal=` compiles a cutfile; a 360/desk/table goal also proposes a `360_assembly_plan`) → review → render → QC → human review. Operator guide: [360_ASSEMBLY.md](../360_ASSEMBLY.md).

**Human residuals:** Renovate host token, directories #88, launch #90. First-10 **closed**. MCPB unsigned is the product path. Real X4 dogfood is optional; synthetic 2:1 fixtures cover the compiler.

**Public site:** `https://kinocut.dev/` `/llms.txt` and homepage stamp **1.15.0** (kinocut-site `11e0d2c`, Netlify prod). Remaining homepage `1.14.1` strings are historical surface comparison.

**Desk residual:** PR **#405** is merged (`dae62af`). Colima lives on the operator M4 Mac, not Mini/nucbox. Do not restart `forgejo-runner` mid-job (exact 80s fail, no `lint-checkout`). Receipt: [2026-08-19-ops-closeout.md](2026-08-19-ops-closeout.md).

**Perf receipt:** cheap CLI + import timings in [golden-path-timings.md](golden-path-timings.md) — baseline only, not an optimized claim.

**Living authority:** [ops closeout 2026-08-19](2026-08-19-ops-closeout.md) · [residual matrix](2026-08-12-residual-maturity-matrix.md) · [HUMAN_GATES](../HUMAN_GATES.md). S+ excellence PRD is local-only (`.omx/plans/`, gitignored).
