# Phase 0 exit receipt — rename distribution verification

**Date:** 2026-10-20  
**Decision:** **GO**, by the owner (Simon Gonzalez De Cruz), 2026-10-20  
**Issue:** GitHub #487  
**Plan:** [trusted-execution plan, Phase 0](../plans/2026-07-09-kinocut-trusted-execution-layer.md#phase-0--kinocut-rename-cutover-identity-pivot)

## Scope

This is a **new verification against the current published release (1.16.1)**,
recorded on 2026-10-20. It does not reconstruct the original Phase 0 cutover
date or substitute today's version for a historical one. The rename criteria
below are checked as they stand now; the owner's GO closes Phase 0 on this
evidence.

## Criteria

| Criterion | Evidence (2026-10-20, UTC) | Result |
| --- | --- | --- |
| Clean installed `kino` CLI | Fresh Python 3.13 virtual environment, `pip install kinocut==1.16.1`: `kino --version` prints `Kinocut 1.16.1`; `kino info` on a generated 1 s H.264 clip returns its metadata, exit 0. | Pass |
| Renamed source repository | GitHub API `repos/KyaniteLabs/kinocut` returns `full_name` `KyaniteLabs/kinocut`, default branch `master`. | Pass |
| Registry listing | MCP Registry `v0/servers/tech.kyanitelabs%2Fkinocut/versions/latest` returns `tech.kyanitelabs/kinocut` 1.16.1, status `active`, `isLatest: true`, published 2026-10-13. Matches `server.json`. | Pass |
| Site/docs identity | https://kinocut.dev/ and `llms.txt` load over HTTPS and identify the product as Kinocut with 203 MCP tools / 177 CLI commands. They still show version 1.16.0; the 1.16.1 site update is tracked in #479. | Pass (identity); version lag tracked |
| Compatibility shim resolves | Fresh virtual environment, `pip install mcp-video`: installs `mcp-video` 1.6.16, which requires and installs `kinocut` 1.16.1; `kino --version` prints `Kinocut 1.16.1`. | Pass |

## Remaining items outside Phase 0

- Site version stamp 1.16.0 → 1.16.1: #479.
- Forgejo mirror activation: #488 / #499.
