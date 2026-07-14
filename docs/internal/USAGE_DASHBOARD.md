# Kinocut internal usage dashboard

**Purpose:** one place for Simon / agents to refresh product traction without inventing telemetry that violates local-first.

## What the dashboard is

| Layer | Path | Job |
| --- | --- | --- |
| Collector | `scripts/collect_usage_metrics.py` | Pull GitHub + PyPI + Registry into JSON |
| Snapshot | `docs/status/usage-metrics-latest.json` | Machine-readable last run |
| Narrative | `docs/status/YYYY-MM-DD-usage-metrics.md` | Human reading + community notes |
| This page | `docs/internal/USAGE_DASHBOARD.md` | How to run + interpret |

## How to refresh

```bash
# needs: gh auth, network; optional GITHUB_TOKEN
python3 scripts/collect_usage_metrics.py
# writes docs/status/usage-metrics-latest.json and prints a summary table
```

Optional: open the JSON in any table viewer; or regenerate a dated markdown note when something material changes (first community PR, release day, star spike).

## Panels (mental model)

1. **Discovery** — stars, forks, GitHub views/uniques, popular paths (rename residual)  
2. **Install** — PyPI recent for `kinocut` **and** `mcp-video` shim  
3. **Identity** — published version, registry status, website URL  
4. **Community** — external human PRs/issues (filter bots)  
5. **Proof** — last golden-path run (local, not remote): operator records pass/fail manually  

## What we refuse to build

- Client-side analytics on kinocut.dev (product promise: no phoning home)  
- Secret MCP call logs from users  
- Vanity public counters that lag or lie  

## Cadence

| When | Action |
| --- | --- |
| After each public release | Run collector; update narrative snapshot |
| Weekly (operator) | Run collector; note clone vs star ratio |
| First community PR/issue | Name author + link in dated metrics note |

## Related

- Public claims: `docs/public_claims.json`  
- Directory board: `docs/DIRECTORY_STATUS.md`  
- Latest narrative: `docs/status/2026-07-14-usage-metrics.md`  
