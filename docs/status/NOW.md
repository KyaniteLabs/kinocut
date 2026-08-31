# Kinocut now

**Published:** 1.15.1 · **196 MCP / 167 CLI** · `docs/public_claims.json`

**Tip (`master`):** 1.15.1 (same counts). Pip history in one line: 1.14.1 = 360 dual-cam + lazy import; 1.15.0 = honest diagnostics + first-class Windows; 1.15.1 (2026-08-31) = registry ownership (shim 1.6.12, #469) + object-matte streaming decode/scratch guards (#412/#414, installable as `kinocut[object-matte]`). Dual-host matched at `060c9cd` (Forgejo #414 stream/scratch port + #415 tip-SHA docs).

**Product pipeline:** Phase 1–4 + Track E **GO**.

**Default agent path:** doctor/info → `video_intent` (`goal=` compiles a cutfile; a 360/desk/table goal also proposes a `360_assembly_plan`) → review → render → QC → human review. Operator guide: [360_ASSEMBLY.md](../360_ASSEMBLY.md).

**Human residuals:** Renovate host token, directories #88, launch #90. First-10 **closed**. MCPB unsigned is the product path. Real X4 dogfood is optional; synthetic 2:1 fixtures cover the compiler.

**Public site:** `https://kinocut.dev/` `/llms.txt` and homepage stamp **1.15.0** (kinocut-site `11e0d2c`, Netlify prod). Remaining homepage `1.14.1` strings are historical surface comparison.

**Desk residual:** Colima is the operator M4 Mac, not Mini. Do not restart `forgejo-runner` mid-job (exact 80s fail). Perf-committee reports are inspect receipts only ([README](perf-committee/README.md)). Receipt: [2026-08-19-ops-closeout.md](2026-08-19-ops-closeout.md).

**Perf receipt:** cheap CLI + import timings in [golden-path-timings.md](golden-path-timings.md) — baseline only, not an optimized claim.

**Living authority:** [ops closeout 2026-08-19](2026-08-19-ops-closeout.md) · [residual matrix](2026-08-12-residual-maturity-matrix.md) · [HUMAN_GATES](../HUMAN_GATES.md). S+ excellence PRD is local-only (`.omx/plans/`, gitignored).
