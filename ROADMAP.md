# Improvement Roadmap

Kinocut 1.15.1 is published with 196 MCP tools and 167 CLI commands (`mcp-video` 1.6.12 shim).

**Published product:** Kinocut **1.15.1** (2026-08-31) · **196 MCP / 167 CLI** · living snapshot [`docs/status/NOW.md`](docs/status/NOW.md)
**Canonical claims:** [`docs/public_claims.json`](docs/public_claims.json)  
**Human-only residuals:** [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md)  
**Residual portfolio (living truth):** [`docs/status/2026-08-12-residual-maturity-matrix.md`](docs/status/2026-08-12-residual-maturity-matrix.md) · [sound residual DAG](docs/status/2026-08-12-sound-residual-stage-dag.md) · [fixture freeze](docs/status/2026-08-12-sound-fixture-freeze.md) · [L1 truth pass](docs/status/2026-08-12-l1-truth-pass.md) · [phase checkpoints](docs/status/PHASE_CHECKPOINTS.md)  
**Excellence program (snapshot):** [`docs/status/2026-08-07-kinocut-excellence-audit.md`](docs/status/2026-08-07-kinocut-excellence-audit.md) · handoff [`docs/handoffs/2026-08-07/kinocut-excellence-campaign.md`](docs/handoffs/2026-08-07/kinocut-excellence-campaign.md)  
**Earlier tip snapshot:** [post-campaign tip status](docs/status/2026-07-27-post-campaign-tip-status.md) (evidence only)

This file is **planning truth for after 1.15.1**. July 2026 status notes and pre-1.3 history live under **Archive** — they are evidence, not current claims. Prefer the **2026-08-12 residual matrix** over any July “S5–S15 incomplete / missing packages” language.

---

## Claim ledger freeze (until L3)

| Rule | Detail |
|------|--------|
| Authority | Only the **ultragoal claim owner** (ledger leader for plan `kinocut-full-build`, or product override in writing) may bump [`docs/public_claims.json`](docs/public_claims.json) |
| Window | **Claim freeze until L3** claim PR (portfolio GO / DEFERRED matrix + dual-host + ROADMAP/PHASE honesty) |
| Non-owners | Do **not** invent tip counts as a release; do not bump `published_*` or surface counts outside the L3 claim PR |
| Human gates | Never invent directory/launch completions; **#92 first-10 is closed** (live adoption supersedes) — see `docs/HUMAN_GATES.md` |

Release ritual still documents *how* to freeze claims at cut time; this freeze **supersedes casual bumps** during residual L1–L2 work.

---

## Current (published 1.15.1)

- **First-class Windows support** — portable projectstore file locking (`fcntl`/`msvcrt`), contention-only lock contract, UTF-8 stdio, `windows-latest` smoke job. `kino --mcp` is importable on Windows.
- **Honest MCP diagnostics** — `kino --mcp` prints the real server-tree import cause; `kino doctor` required `mcp-server-import` check.
- **360 dual-cam assembly** — `360_assembly_plan` via `video_intent` `goal=` + Client methods; approve then render. Operator guide: [`docs/360_ASSEMBLY.md`](docs/360_ASSEMBLY.md). Not a new MCP name. Not an optimized-AI-director claim. Shipped in 1.14.1; still current.
- **PEP 562 lazy import** — `import kinocut` no longer eager-loads Client/engines
- **Ship-seam honesty** — QC-80 documented on CLI/Client `repurpose` / `shorts-package`; durable MCP `video_repurpose` does not apply `min_score`
- **Committee perf top-10** — single-pass 360 graph, sampled QC, SHA cache, lazy CLI/import/search_tools, doctor skips unused `npx --yes`
- Intent / watching foundation, TE multipliers (audiogram, brand kit, punch zoom, seek, OTIO), still/plate, workflow + receipts
- Rescue, compositing, Hyperframes, repurposing package surface
- **Sound honesty:** `kinocut_sound/` packages for design stages S4–S13 exist on tip; public MCP/CLI join remains a **thin S12** surface (6 tools) — **not** full-episode sonic-world product complete. Synthetic S14 dual-class evidence exists (`docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json`) but **≠** product claim; residual class is re-run/deepen (see residual matrix + sound DAG). Do **not** staff greenfield “S5–S15 incomplete” rebuilds without a failing case.
- Dual-host public face restored; S+ **floor** green (excellence WP-A targets ≥95 preferred, not hard portfolio GO)
- Policy hygiene on tip: modules ≤800 LOC (incl. `hyperframes_ops` split), functions ≤80, ruff clean — excellence WP-C/D/G **done** (2026-08-12 live). Do not re-open size rebuilds from the 2026-08-07 audit snapshot alone.
- Security claim-audits C1/M1: **verify-only pass** (2026-08-12) — see [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md) and `.omx/state/l0-claim-audit.md`

Do not re-list older 1.9–1.12 waves here as open work — they are published history (see Archive / CHANGELOG).

---

## Next (agent-eligible residual / excellence)

Ordered per residual matrix + excellence audit. Prefer one work package per PR. **Residual-only:** no re-implement of `verify-only` without a failing case.

| WP | Outcome | Notes |
|----|---------|--------|
| **A** S+ max + site stamp | README overall ≥95 preferred; site `llms.txt` date current | **Floor 100/100/100** verified 2026-08-15 (`verify-readme-splus`); preferred, **not** hard portfolio GO |
| **B** Docs truth | L1.2 false-done punch list; residual matrix links | **L1.2 closed 2026-08-12** — see [L1 truth pass](docs/status/2026-08-12-l1-truth-pass.md); keep living docs aligned |
| **G** Ruff hygiene | `ruff check kinocut` clean | **Done on tip** (2026-08-12 live) |
| **C** Module size policy | ≤800 LOC modules | **Done** — engine/workflow splits + 2026-08-12 `hyperframes_ops`→helpers (ops ≤800; guardrail locks ops/helpers) |
| **D** Long functions | ≤80 LOC functions | **Done on tip** (0 funcs >80, 2026-08-12 live) |
| **F** Perf baselines | Golden-path p50/p95 | **Measured** 2026-08-12 + 2026-08-15 (import seam PEP 562) in [golden-path-timings.md](docs/status/golden-path-timings.md); not an “optimized” product claim |

**L2 residual (ultragoal, capacity-capped):** sound residual waves per [sound residual DAG](docs/status/2026-08-12-sound-residual-stage-dag.md); Phase 3/4 deepen → GO or DEFERRED; cutfile render or DEFERRED; TE/conversational/MCPB honesty. See [product pipeline complete](docs/status/2026-08-12-product-pipeline-complete.md) and residual matrix.

---

## Human / gated (not agent-closable alone)

| Item | Owner | Source |
|------|-------|--------|
| Directories (#88), launch posts (#90), Renovate host token (#3) | Human/ops | Optional marketing/ops — not product phase blockers |
| CI `light` vs `heavy` runner topology | Ops | Partial |
| First-10 users (#92) | — | **Closed 2026-08-12** — adoption already past gate (107 GitHub stars; ~23k PyPI downloads last month). See `docs/HUMAN_GATES.md` |

Product phases 1–4 + Track E are **GO** on tip (1.15.1). Agents must not invent third-party directory approvals. Do **not** re-open #92 as incomplete.

---

## Archive (historical — not current planning)

Pre-1.13 archaeology (v1.2.x Remotion/Revideo notes, wishlist drafts) lives in
[`docs/archive/roadmap-pre-1.13.md`](docs/archive/roadmap-pre-1.13.md).
Prefer CHANGELOG + the **2026-08-12 residual matrix** for current truth.
