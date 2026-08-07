# Handoff: Kinocut excellence campaign (S+ → amazing → optimized)

**Date:** 2026-08-07  
**Source of truth:** Forgejo `https://git.kyanitelabs.tech/KyaniteLabs/kinocut` (`master`)  
**GitHub:** mirror only (`KyaniteLabs/kinocut`) — do not land public faces GH-only  
**Workspace:** `~/workspaces/kinocut` (compat symlink `~/workspaces/mcp-video` → `kinocut`)  
**Live tip (verified):** `9d85de5351c54b8dd538114e43ebda937442988f`  
**Published:** Kinocut **1.13.0** · **194 MCP / 165 CLI** · `mcp-video==1.6.4` shim  
**Companion audit:** [`docs/status/2026-08-07-kinocut-excellence-audit.md`](../../status/2026-08-07-kinocut-excellence-audit.md)

Cold-start dispatch (paste into next agent):

```bash
cd ~/workspaces/kinocut   # or: cd ~/workspaces/mcp-video  (symlink)
git fetch origin && git checkout master && git pull --ff-only origin master
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)"
cat docs/handoffs/2026-08-07/kinocut-excellence-campaign.md
cat docs/status/2026-08-07-kinocut-excellence-audit.md
# if Forgejo auth expired: git credential fill for git.kyanitelabs.tech; fj api GET user
```

---

## 1. Purpose

Drive Kinocut from **“1.13.0 published + S+ floor pass”** to a falsifiable **excellence bar**: full-fleet S+ max (or intentional exceptions), public-doc truth with zero stale product claims, feature programs closed with evidence (or explicitly human-gated), and code within project size/quality policy with measured optimization.

## 2. Why it matters

1.13.0 is a real ship, but **floor ≠ excellence**. README/S+ can green while modules violate 800-LOC policy, ROADMAP still mixes 1.2/1.3 history with 1.13 open gates, site stamps lag, and “amazing features” still list human residuals + post-release phases. Without a sequenced campaign, agents thrash on polish or overclaim.

## 3. Exact files

**Read first (authority / claims):**

| Path | Why |
|------|-----|
| `docs/status/2026-08-07-kinocut-excellence-audit.md` | Full diagnosis + work packages |
| `docs/public_claims.json` | Canonical version/tool counts |
| `README.md`, `llms.txt` | Public face |
| `docs/HUMAN_GATES.md` | Human-only residual |
| `ROADMAP.md` | Open vs claimed (needs rewrite for post-1.13) |
| `Agents.md` | LOC/function limits, FFmpeg safety |
| `~/.agents/docs/README-S-PLUS.md` | S+ floor doctrine |
| `~/.agents/docs/DUAL-HOST-AUTHORITY.md` | Forgejo-first |

**Likely touch by workstream:**

| Stream | Paths |
|--------|--------|
| S+ max | `README.md`, optional `llms.txt`, site `kinocut-site/llms.txt` + `index.html` |
| Docs truth | `ROADMAP.md`, `docs/status/*`, `docs/INSTALL.md`, skills if versioned |
| Code policy | `kinocut/hyperframes_engine.py`, `kinocut/workflow/executor.py`, large CLI handlers |
| Features | `kinocut/watching/`, `kinocut/multipliers/`, `kinocut_sound/`, MCPB docs |
| Verify | `tests/test_public_claims.py`, `docs/public_claims.json` |

## 4. Exact commands

```bash
cd ~/workspaces/kinocut
git status -sb && git log -1 --oneline

# Claims
python3 -c "import json; print(json.load(open('docs/public_claims.json')))"
python3 -c "import kinocut; print(kinocut.__version__)"

# S+ / dual-host
python3 ~/.agents/bin/s_plus_engine.py score KyaniteLabs/kinocut
verify-readme-splus 2>&1 | grep -iE 'kinocut|ok=|fail='
verify-dual-host-readmes --splus 2>&1 | tail -30

# Policy
python3 - <<'PY'
from pathlib import Path
import ast
over_m, over_f = [], []
for p in Path('kinocut').rglob('*.py'):
    if '__pycache__' in str(p): continue
    n = sum(1 for _ in open(p, errors='replace'))
    if n > 800: over_m.append((n, str(p)))
    try: t = ast.parse(open(p, errors='replace').read())
    except Exception: continue
    for node in ast.walk(t):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, 'end_lineno', None) or node.lineno
            if end - node.lineno + 1 > 80:
                over_f.append((end-node.lineno+1, f'{p}:{node.name}'))
print('modules>800', len(over_m), over_m[:10])
print('funcs>80', len(over_f), sorted(over_f, reverse=True)[:10])
PY

# Lint / tests (PR-safe)
ruff check kinocut
python3 -m pytest tests/ -q -m "not slow" -n 4 --tb=line
# Full before release claims
python3 -m pytest tests/ -x -q --tb=short

# Dual-host live README
gh api repos/KyaniteLabs/kinocut/contents/README.md --jq '{size,sha}'
# FJ via: fj api GET 'repos/KyaniteLabs/kinocut/contents/README.md?ref=master'
```

**Land public face:** Forgejo branch → PR → `fj merge` / `{"Do":"merge","force_merge":true}` → verify tip SHA/size → allow `sync-github` or repair mirror if GH diverges (see dual-host docs; do not GH-only README loops).

## 5. Constraints

| Constraint | Rule |
|------------|------|
| Host | **Forgejo first**; GitHub is mirror |
| Claims | Never invent directory listings, first-10 users, launch metrics, signed MCPB complete |
| Versions | `docs/public_claims.json` is source for published counts; tip may equal published after cutover |
| Safety | Escape FFmpeg filter values; timeouts on all subprocess; custom errors from `errors.py` |
| Size | Module ≤800 LOC; function ≤80 lines (`Agents.md`) — **currently violated** |
| Models | Use Pushing Dispatch before subagent/model pick; no vision on GLM lanes |
| Scope | Do not force-push Forgejo `master`; GH force only for **mirror repair when FJ is good** + ruleset protocol |
| Budget | Prefer phased PRs: (A) S+/docs truth → (B) LOC split → (C) feature finish → (D) perf |

## 6. Definition of done (falsifiable)

**Campaign “S+ excellence” is done only when all of the following are true with evidence:**

| # | Gate | Threshold |
|---|------|-----------|
| D1 | Kinocut README S+ | `overall ≥ 95` **or** documented intentional misses ≤2 soft SEO items with rationale |
| D2 | Dual-host | FJ and GH README **same size + blob SHA**; no `1.11.x` as latest |
| D3 | Site GEO | `kinocut.dev/llms.txt` `Last-updated` within 7 days of tip; claims match `public_claims.json` |
| D4 | Docs truth | `ROADMAP.md` top section is **post-1.13.0** only; historical 1.2/1.3 moved under archive heading; open items match `HUMAN_GATES` + audit WP list |
| D5 | Code policy | **0** modules >800 LOC under `kinocut/`; **0** new functions >80 lines; plan to clear backlog of 65 long functions (or inventory with owners) |
| D6 | Lint | `ruff check kinocut` **0** errors (or waived with ADR) |
| D7 | Tests | `pytest tests/ -m "not slow"` green; full suite green before any version bump |
| D8 | Features “amazing” | Each open feature in audit §4 has either **(a)** shipped + tested + claimed in public_claims, **(b)** explicit human-gate row, or **(c)** deferred with ticket ID — no silent half-claims |
| D9 | Optimization | Hot path profile or documented baseline: workflow render + trim golden path; no “optimized” without before/after or complexity note |

## 7. Required evidence

Attach to closeout:

1. `python3 ~/.agents/bin/s_plus_engine.py score KyaniteLabs/kinocut` output  
2. Dual-host size/SHA match snippet  
3. `docs/public_claims.json` + PyPI/registry version check  
4. Module/function policy script output (D5)  
5. Pytest summary line counts  
6. List of PRs (Forgejo numbers) per work package  
7. For feature WPs: test file paths + claim map  

## 8. What NOT to touch

- Do **not** re-hollow README for “token efficiency”  
- Do **not** claim directories / first-10 / launch complete without human evidence  
- Do **not** bump major surface counts without updating `public_claims.json` + tests  
- Do **not** remove `mcp_video` compat or `mcp-video` shim on 1.13.x without explicit compat ADR  
- Do **not** GH-only public-face rewrites  
- Avoid drive-by refactors outside the active work package  
- Secrets, tokens, machine-local paths never in public docs  

## 9. Report format

Bottom-line first:

```text
STATUS: green | yellow | red
WP completed: [ids]
Still open: [ids + owner human|agent]
S+ overall: N (misses: …)
Dual-host: match|drift
Policy: modules>800=N funcs>80=N
Tests: … passed
Needs-you: [human gates only]
```

## 10. Mode

| Mode | When |
|------|------|
| **Inspect-only** | First session after this handoff: re-run audit commands; confirm tip still `9d85de5` or note drift |
| **Edit** | After picking one work package (A→D order preferred) |
| **Stop-and-ask** | Version bump/release; GH ruleset disable; force-push; deleting compat; claiming human-gate outcomes; spend >1 day on LOC split without tests green |

---

## Recommended execution order (next agent)

1. **WP-A** — S+ max + site `Last-updated` + dual-host recheck (hours)  
2. **WP-B** — ROADMAP + status doc truth rewrite (hours)  
3. **WP-C** — Split `hyperframes_engine.py` + `workflow/executor.py` under 800 LOC (1–3 days)  
4. **WP-D** — Long-function CLI handler decomposition (multi-day)  
5. **WP-E** — Feature programs per audit §4 (watching/sound/MCPB/CI topology) — human co-owned  
6. **WP-F** — Perf/optimization baselines (after structure stable)  

Full diagnosis, prioritization, effort, and risks: **`docs/status/2026-08-07-kinocut-excellence-audit.md`**.
