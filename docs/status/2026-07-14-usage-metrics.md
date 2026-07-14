# Kinocut usage metrics snapshot

**Captured:** 2026-07-14 (approx. 06:15–06:35 UTC)  
**Scope:** product identity **Kinocut** (formerly mcp-video), not the KyaniteLabs org aggregate.  
**Method:** GitHub REST traffic + contributors + PRs; PyPI Stats API; MCP Registry JSON.

Refresh: `python scripts/collect_usage_metrics.py`

---

## Headline (evidence-backed)

| Signal | Value | Source |
| --- | ---: | --- |
| GitHub stars | **77** | `repos/KyaniteLabs/kinocut` |
| Forks | **20** | same |
| GitHub views (≈14d) | **884** views / **465** uniques | traffic/views |
| GitHub clones (≈14d) | **1,567** clones / **475** uniques | traffic/clones |
| PyPI `kinocut` recent | **845** last day · **3,227** last week · **3,227** last month | pypistats recent |
| PyPI `mcp-video` (compat) | **596** last day · **4,266** last week · **11,617** last month | pypistats recent |
| Latest published package | **1.7.0** (2026-07-10) | PyPI + GitHub release + MCP Registry |
| MCP Registry | **active** `io.github.KyaniteLabs/kinocut` @ 1.7.0 | registry API |
| Community human PR | **#361** `betsmayank` — hyperframes MCP hang fix, **merged 2026-07-13** | GitHub PR |

**Reading:** Install/clone volume is strong relative to stars (clones ≈20× stars in the traffic window). Dual package traffic (`kinocut` + legacy `mcp-video`) means discovery still splits across the rename.

---

## First community contribution (today relative to product week)

| Field | Value |
| --- | --- |
| PR | https://github.com/KyaniteLabs/kinocut/pull/361 |
| Author | **betsmayank** (human, not bot) |
| Title | `fix(hyperframes): prevent init from hanging under MCP (no TTY)` |
| Merged | 2026-07-13T21:06:33Z |
| Why it matters | Real external contributor fixed an MCP-critical hang; 89 hyperframes tests + e2e note |
| Contributor graph | `betsmayank` appears with **1** contribution (first external human after maintainer/bots) |

This is the first non-maintainer, non-bot product PR of record on the public GitHub graph for Kinocut.

---

## Traffic paths (top)

Still heavy on the **old slug** path:

1. `/KyaniteLabs/mcp-video` — 480 views / 314 uniques (rename residual)  
2. `/KyaniteLabs/kinocut` — 186 / 126  
3. Skill / demo deep links under old tree still get residual hits  

**Action:** keep redirect/compat messaging; directories should cite `kinocut` only.

---

## PyPI daily (`kinocut`, with mirrors)

| Date | Downloads |
| --- | ---: |
| 2026-07-10 | 969 |
| 2026-07-11 | 1177 |
| 2026-07-12 | 762 |
| 2026-07-13 | 855 |

---

## What we cannot honestly claim (yet)

- Public **MCP tool-call volume** (no product telemetry; local-first by design)  
- **kinocut.dev** pageviews (GitHub Pages has no built-in analytics; product refuses marketing cookies)  
- Unique “active weekly operators” without a privacy-preserving opt-in  

---

## Internal dashboard (how we operate this)

See [USAGE_DASHBOARD.md](../internal/USAGE_DASHBOARD.md).
