# Kinocut full excellence audit — diagnosis & recommendations

**Date:** 2026-08-07  
**Auditor context:** post-1.13.0 campaign closeout + max-reach README land (#288) + local workspace rename  
**Authority tip:** `9d85de5351c54b8dd538114e43ebda937442988f` (Forgejo `master` = GitHub `master` after mirror repair)  
**Handoff:** [`docs/handoffs/2026-08-07/kinocut-excellence-campaign.md`](../handoffs/2026-08-07/kinocut-excellence-campaign.md)  
**Verdict class:** **Strong ship / incomplete excellence program**

> **Post-audit residual note (2026-08-12):** WP-C/D/G size/ruff false-dones are **closed on tip**
> (L0/L1 truth). Living residual staffing uses
> [`2026-08-12-residual-maturity-matrix.md`](2026-08-12-residual-maturity-matrix.md)
> and [L1 truth pass](2026-08-12-l1-truth-pass.md). Do not re-staff module/function splits
> from §2.3 / WP-C/D below without a new failing policy case. S+ ≥95 remains preferred open.

---

## 0. Executive summary

| Layer | Grade (honest) | One line |
|-------|----------------|----------|
| **Product ship (1.13.0)** | **A−** | Real PyPI, registry, release, 194/165, claims JSON aligned |
| **Public face / S+ floor** | **A− / B+** | Dual-host match, S+ **passes** (~89–93), not maxed; site date stamp lag |
| **Documentation system** | **B** | Core claims true; ROADMAP and status corpus still multi-era / partially stale framing |
| **Feature completeness vs “amazing”** | **B−** | Large surface shipped; watching/sound/MCPB/CI/human programs still open or gated |
| **Code structure / policy** | **C+** | ~80k LOC package; **2 modules >800**, **~65 functions >80**; ruff still finds fixables |
| **Optimization** | **C** | No campaign-level perf baseline; heavy CI on single runner class; structure first |

**Bottom line:** Kinocut is **not** broken and **not** hollow. It is **not** “entire project S+ + every feature amazing + all code optimized.” Treat excellence as a **multi-work-package program**, not one PR.

---

## 1. What is already true (do not re-solve)

### 1.1 Published product

| Fact | Evidence |
|------|----------|
| Version **1.13.0** | `pyproject.toml`, `kinocut.__version__`, PyPI, GH release `v1.13.0` |
| Surface **194 MCP / 165 CLI** | `docs/public_claims.json`, README, registry package meta |
| Compat **mcp-video 1.6.4 → kinocut 1.13.0** | PyPI `requires_dist` |
| MCP Registry active @ 1.13.0 | registry official meta `updatedAt` 2026-08-07 |
| Test inventory | **4914** tests collected; **293** `test_*.py` files |

### 1.2 Dual-host public face (as of audit)

| Host | README size | SHA (blob) | Content truth |
|------|-------------|------------|---------------|
| Forgejo | 40072 | `2e5d01e94a3d…` | 1.13.0 max-reach face, S+ marker, 2× `mcpServers` |
| GitHub | 40072 | `2e5d01e94a3d…` | **MATCH** (post force-mirror repair of 1.11.1-era tip) |

PR **#288** restored full reach content after hollow compress (#286) and thin rewrite (#287).

### 1.3 S+ floor (fleet + Kinocut)

| Check | Result |
|-------|--------|
| `verify-readme-splus` fleet | **42/42 OK** (floor overall ≥85) |
| Kinocut score (engine) | **overall 89.3** miss: `seo_keywords_early`, `seo_toc`, `geo_entity_def` |
| Live `score_readme` on tip blob | **overall 92.6** miss: `seo_keywords_early`, `geo_entity_def` |

**Interpretation:** S+ **floor is green**. Excellence target should be **≥95 overall** and/or zero unexplained misses—not “already perfect.”

### 1.4 Local workspace

| Item | State |
|------|--------|
| Canonical dir | `~/workspaces/kinocut` |
| Compat | `~/workspaces/mcp-video` → symlink to `kinocut` |
| Live agent configs | Updated to `kinocut` path (claude/codex/grok/herdr) |

---

## 2. Diagnosis by domain

### 2.1 SEO / GEO / public face (S+)

**Healthy**

- Entity, TL;DR, FAQ, audience, status, agent surface, install, license, marker present  
- Best-fit search line; dual MCP configs; host list includes Windsurf/Cline  
- Capability depth sections (workflow, rescue, compositing, What Agents Can Do)

**Gaps**

| Gap | Severity | Work |
|-----|----------|------|
| Soft S+ misses (`seo_keywords_early`, `geo_entity_def`, sometimes `seo_toc`) | Low–med | Tighten first-2k-char keyword placement; explicit one-sentence entity definition scorer likes; nav/TOC structure |
| Site `llms.txt` **Last-updated: 2026-07-28** while claims are 1.13.0 | Low (cosmetic but GEO-smelly) | Bump stamp + redeploy site |
| Repo vs site `llms.txt` format drift | Low | Sync from one generator or single source |
| Skill files unversioned | OK | Keep timeless unless release skill needs counts |

### 2.2 Documentation corpus

**Healthy**

- `docs/public_claims.json` is correct and testable  
- `docs/HUMAN_GATES.md` honest  
- Release notes / CHANGELOG carry history properly  
- Deep feature docs exist (STILL_PLATES, WORKFLOWS, RESCUE, etc.)

**Gaps**

| Gap | Severity | Work |
|-----|----------|------|
| **ROADMAP.md** still led by post-1.13 open items **and** large “Planned for v1.3.0” / v1.2 history without clear archive boundary | Med | Rewrite top: Current / Next / Archive |
| Status files dated **July 2026** still linked as “current truth” from ROADMAP | Med | Point ROADMAP only at this audit + HUMAN_GATES; archive older status |
| Not every deep doc re-audited for 1.13 intent/TE language | Low | Sweep INSTALL/PROMPTS/TOOLS intros against public_claims |
| Spanish site/README depth uneven | Low | Optional ES parity pass |

### 2.3 Features vs “amazing”

Roadmap and campaign residue still list unfinished or human-gated programs:

| Area | State (audit) | “Amazing” requires |
|------|---------------|--------------------|
| Intent / watching / TE (1.13) | **Published** | Dogfood + real-media slow tests green; operator docs |
| Still/plate (1.12) | **Published** | Keep receipts/gate honest; fixture pack |
| Workflow + receipts | Shipped; executor **1000 LOC** | Split + resume/recovery docs UX |
| Rescue / compositing / Hyperframes | Shipped; Hyperframes **1302 LOC** | Split engine; Node/Hyperframes doctor UX |
| **Phase 3 watching** (post-release) | Open / gated | Spec + tests + claim bump or stay gated |
| **Phase 4 multipliers / TE expansion** | Open / gated | Same |
| **Full-episode kinocut_sound** | Thin S12 join only; full sonic world **unclaimed** | Explicit program; do not market as complete |
| **MCPB native signed multi-platform** | Foundations only | Supply-chain + human release review |
| **CI runner topology** | Partial (`heavy` used because `light` unavailable) | Admin/runner fleet work |
| **G004** listening / phone-frame multi-minute fixtures | Human-only open | Fixtures + acceptance, not agent fiction |
| **Directories / launch / first-10** | Prep only (`HUMAN_GATES`) | Human operators |

### 2.4 Code quality & policy (`Agents.md`)

| Metric | Observed | Policy | Gap |
|--------|----------|--------|-----|
| Package Python LOC (`kinocut/`) | **~79 755** | n/a | Large product—expect splits |
| Modules **>800 LOC** | **2** (`hyperframes_engine.py` 1302, `workflow/executor.py` 1000) | **0** | **Hard fail** |
| Borderline 700–800 | Several (composite 800, client media 794, audio core 787, …) | Risk | Prevent regressions |
| Functions **>80 lines** | **~65** | **0** (strict) | **Hard fail** backlog |
| Worst functions | CLI handlers 150–334 lines; rescue render 287; design text 187 | Split by command family | Multi-PR |
| Ruff on `kinocut` | **18** issues (12 auto-fixable) | Clean | Quick win |
| Architecture | Engines + server_tools_* + client mixins + CLI | Good spine | Keep; avoid new megafiles |

### 2.5 Optimization / performance

| Observation | Implication |
|-------------|-------------|
| No campaign-level golden-path timing budget in status | Cannot claim “optimized” |
| Slow suite serial on `heavy`; PR suite `-n 4` | Reasonable; topology still fragile |
| FFmpeg-bound work dominates | Optimize batching, probe cache, avoid double probe—not micro-LOC |
| Large CLI dispatch functions | Cold start / maintainability more than CPU |

**Optimization without structure first** will churn. Order: **policy split → hot-path measure → targeted cache/probe work.**

### 2.6 Security / safety (spot)

| Area | Notes |
|------|--------|
| Project-store threat model | Documented under `docs/security/` |
| Recent hardenings | Path validation on caption/brand/OTIO (1.13 campaign) |
| Ongoing | Every new filter string must use `_escape_ffmpeg_filter_value`; subprocess timeouts |
| Recommendation | Periodic security pass on new intent/TE write paths; no “full clean” claim without scoped review |

### 2.7 Dual-host / ops risk

| Risk | Why it bit us | Mitigation |
|------|----------------|------------|
| GH tip stuck on 1.11.1 while FJ advanced | Diverged histories + non-FF ruleset | After FJ land, verify GH tip; mirror workflow + emergency ruleset protocol |
| Hollow README campaigns | Wave2 compress | S+ floor verifiers; refuse compress-as-S+ |
| CI label `light` unavailable | Jobs forced onto `heavy` | Ops ticket; don’t paper over in product claims |

---

## 3. Target excellence model (define “done” before work)

Avoid superlatives without thresholds. Use three ladders:

### Ladder A — Public S+ excellence

| Metric | Floor (today) | Excellence |
|--------|---------------|------------|
| S+ overall | ≥85 | **≥95** |
| SEO / GEO | ≥80 each | **≥95 each** or ≤1 soft miss documented |
| Dual-host README | not hollow | **byte-identical claims face** |
| Site + registry + PyPI | any 1.x | **same version story within 24h of cut** |

### Ladder B — Feature excellence

For each capability family:

1. **Contract** (tool names, fail-closed errors)  
2. **Tests** (unit + at least one real-media or golden path)  
3. **Docs** (TOOLS/CLI/skill mention)  
4. **Claim** (`public_claims` or explicit “not claimed”)  
5. **Human gate** only when external (directories, signing, real users)

### Ladder C — Code excellence

| Metric | Target |
|--------|--------|
| Modules >800 LOC | **0** |
| Functions >80 lines | **0** new; backlog burn-down tracked |
| Ruff | **0** errors on `kinocut` |
| Dead code | zero unused public exports (periodic) |
| Perf | Documented golden-path p50/p95 on reference machine |

---

## 4. Work packages (what work is needed)

Effort is **order-of-magnitude** for a competent agent+human pair, not a bid.

### WP-A — S+ max + face hygiene (0.5–1 day)

| Task | Output |
|------|--------|
| Fix README soft misses (keywords early, entity def, TOC if needed) | S+ overall ≥95 preferred |
| Sync site `llms.txt` Last-updated + claim parity | Netlify/prod deploy |
| Re-run dual-host + `verify-readme-splus` | Evidence attached |
| Optional: generator for README S+ block from `public_claims.json` | Drift-proof |

**Depends on:** none  
**Risk:** low  

### WP-B — Documentation truth rewrite (1–2 days)

| Task | Output |
|------|--------|
| Rewrite `ROADMAP.md` top for post-1.13 | Current / Next / Human / Archive |
| Retire “current truth → July status” pointers | Link this audit + HUMAN_GATES |
| Sweep top docs for stale “latest is 1.11/1.12” | Zero false latest |
| Align skill frontmatter only if needed | Timeless OK |

**Depends on:** none  
**Risk:** low (narrative only)  

### WP-C — Module size policy (2–5 days)

| Module | Action |
|--------|--------|
| `kinocut/hyperframes_engine.py` (1302) | Split: process/cli wrapper, validate, render, stills, pipeline helpers |
| `kinocut/workflow/executor.py` (1000) | Split: plan, render loop, recovery, receipts |
| Borderline 750–800 files | Soft freeze: no net growth without extract |

**Acceptance:** policy script reports **0** modules >800; tests for workflow + hyperframes green.

**Risk:** med (import cycles, public API surface)  

### WP-D — Function size / CLI decomposition (3–7 days)

Priority long functions (from AST audit):

1. `cli/handlers_media.py:handle_media_commands` (~334)  
2. `cli/handlers_core.py:handle_initial_command` (~289)  
3. `rescue/renderer.py:render_rescue` (~287)  
4. Hyperframes / effects / audio handlers & parsers (150–250)  

**Pattern:** one handler family → `handlers_<family>/` with per-command functions; keep CLI entry thin.

**Risk:** med–high (regression in CLI); need targeted tests per command group.

### WP-E — Feature programs (weeks; multi-owner)

| Sub | Owner | Outcome |
|-----|-------|---------|
| E1 Watching Phase 3 | Agent + product | Spec → implement → tests → claim or keep gated |
| E2 Multipliers / TE Phase 4 | Agent + product | Same |
| E3 Full-episode sound | Agent + sound program | Honest roadmap; no partial marketing |
| E4 MCPB production pack | Human + agent | Signing, platforms, clean-machine gates |
| E5 G004 fixtures | Human + agent | Real multi-minute / phone-frame acceptance |
| E6 Human gates #88/#90/#92/#3 | **Human only** | Directories, launch, first-10, Renovate token |

### WP-F — Optimization (after C/D stabilize) (2–5 days initial)

| Task | Output |
|------|--------|
| Define golden path benchmark (doctor → trim → caption → resize → checkpoint) | Script + timings |
| Profile double-ffprobe / workflow render | Top 3 waste list |
| Optional probe cache / batch validate | PR with before/after |
| CI: restore `light` vs `heavy` topology | Ops + workflow truth |

### WP-G — Hygiene quick wins (0.5 day)

| Task | Output |
|------|--------|
| `ruff check --fix` safe auto-fixes | Cleaner tree |
| Confirm no new F401/UP035 debt | CI green |
| Optional mypy scope on `kinocut/contracts` / public client | Typed public edge |

---

## 5. Prioritized roadmap (recommended sequence)

```text
Week 0 (now)
  └─ WP-A S+ max + site stamp
  └─ WP-B ROADMAP/docs truth
  └─ WP-G ruff hygiene

Week 1–2
  └─ WP-C module splits (hyperframes, workflow)
  └─ Start WP-D on worst CLI handlers

Week 2–4
  └─ WP-D continue
  └─ WP-F baseline timings
  └─ WP-E only with explicit product pick (sound vs watching vs MCPB)

Ongoing human track
  └─ WP-E6 HUMAN_GATES (parallel, not agent-blocked)
```

Do **not** start “optimize everything” or “rewrite audio engine” until WP-C acceptance is green.

---

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| README excellence PR re-hollowed | Med | High | S+ verifier in CI or pre-merge checklist |
| GH mirror diverges again | Med | High | Post-merge dual-host size check; document ruleset protocol |
| LOC split breaks public imports | Med | High | Keep re-exports; full hyperframes/workflow tests |
| Agent claims human gates done | Med | High | HUMAN_GATES + claim-audit |
| Scope explosion “amazing all features” | High | High | One WP-E stream at a time; falsifiable D8 |

---

## 7. Explicit non-goals (this program)

- Renaming the **PyPI package** again  
- Dropping `mcp_video` / `mcp-video` compat on 1.13.x without ADR  
- Competing with cloud editors on generative video volume  
- Declaring directories/launch/first-10 complete without operator evidence  
- Full rewrite of FFmpeg stack  

---

## 8. Measurement dashboard (re-run each session)

```bash
# Identity
git -C ~/workspaces/kinocut rev-parse --short HEAD
python3 -c "import json;print(json.load(open('docs/public_claims.json'))['published_version'])"

# S+
python3 ~/.agents/bin/s_plus_engine.py score KyaniteLabs/kinocut

# Policy
# (module/function script from handoff §4)

# Quality
ruff check kinocut | tail -5
python3 -m pytest tests/ -q -m "not slow" -n 4 --tb=no | tail -3
```

Record results in a short ledger under `docs/status/` if running multi-day.

---

## 9. Recommendations (decision-ready)

1. **Accept** 1.13.0 as a solid **ship floor**, not excellence complete.  
2. **Fund WP-A + WP-B immediately** (cheap, high trust).  
3. **Fund WP-C as the first engineering excellence milestone** (policy is currently red).  
4. **Pick one WP-E feature theme** for the next release train; park the rest as gated.  
5. **Keep human gates human**; agents prepare only.  
6. **WP-F only after** structure metrics improve—otherwise “optimization” is folklore.  
7. **Re-verify dual-host** after every public-face PR (size + SHA, not `merged: true`).  

---

## 10. Appendix — evidence snapshot (2026-08-07)

| Item | Value |
|------|--------|
| Tip SHA | `9d85de5351c54b8dd538114e43ebda937442988f` |
| README blob size | 40072 (FJ = GH) |
| Tests collected | 4914 |
| `kinocut/` LOC | ~79755 |
| Modules >800 | 2 |
| Functions >80 | ~65 |
| Ruff issues (`kinocut`) | 18 |
| S+ Kinocut | 89.3–92.6 (pass, not max) |
| Human residual | Renovate token, directories, launch, first-10 |

---

## 11. Document control

| Field | Value |
|-------|--------|
| Type | Diagnosis + recommendations (not a status-final) |
| Confidence | High on tip/claims/policy counts; medium on feature “Phase 3/4” detail (roadmap-level) |
| Revalidate | After any release cut, README campaign, or major module split |
| Owner | Next excellence-campaign agent + Simon for human gates |
