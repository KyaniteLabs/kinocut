# Kinocut now

**Published:** 1.14.1 · **196 MCP / 167 CLI** · `docs/public_claims.json`  
**Tip (`master`):** 1.15.0 unreleased (same counts). 360 dual-cam assembly and PEP 562 lazy `import kinocut` are in pip **1.14.1**. Honest-diagnostics (`--mcp` import errors, doctor `mcp-server-import`) is on this tip, **not** on PyPI yet.

**Product pipeline:** Phase 1–4 + Track E **GO**.

**Default agent path:** doctor/info → `video_intent` (`goal=` compiles a cutfile; a 360/desk/table goal also proposes a `360_assembly_plan`) → review → render → QC → human review. Operator guide: [360_ASSEMBLY.md](../360_ASSEMBLY.md).

**Human residuals:** Renovate host token, directories #88, launch #90. First-10 **closed**. MCPB unsigned is the product path. Real X4 dogfood is optional; synthetic 2:1 fixtures cover the compiler.

**Perf receipt:** cheap CLI + import timings in [golden-path-timings.md](golden-path-timings.md) — baseline only, not an optimized claim.

**Living authority:** [residual matrix](2026-08-12-residual-maturity-matrix.md) · [HUMAN_GATES](../HUMAN_GATES.md). S+ excellence PRD is local-only (`.omx/plans/`, gitignored).
