# Governance & stewardship (GOV.1)

**Status:** living doc · **Date:** 2026-08-07  
**Issue:** Forgejo #91

## Why this exists

Single-maintainer open-source tools attract a fair bear case: bus factor, silent
abandonment, and opaque release decisions. Kinocut counters that with **visible
stewardship** — not performance theater.

## What is public

| Surface | Where |
| --- | --- |
| Source of truth | Forgejo `KyaniteLabs/kinocut` (`git.kyanitelabs.tech`) |
| Collaboration mirror | GitHub `KyaniteLabs/kinocut` |
| License | Apache-2.0 |
| Releases | Annotated tags `v*`, CHANGELOG, dual PyPI (`kinocut` + `mcp-video` shim) |
| Security model | [`PROJECTSTORE_THREAT_MODEL.md`](PROJECTSTORE_THREAT_MODEL.md) |
| Agent skill | `skills/kinocut/SKILL.md` |
| Public claims | `docs/public_claims.json` (published vs development counts) |

## Decision record hygiene

- Architecture decisions: `docs/adr/`
- Phase plan: `docs/plans/2026-07-09-kinocut-trusted-execution-layer.md`
- Phase go/no-go: [`PHASE_CHECKPOINTS.md`](../status/PHASE_CHECKPOINTS.md)

## Maintainer commitments (honest)

1. **No silent public-face hollowing** — dual-host README/S+ floor applies.
2. **No invented human gates** — listening/user programs stay human-owned.
3. **Release claims match packages** — `public_claims.json` is the lockstep file.
4. **Security findings** route through the threat model and fail-closed defaults.

## How to contribute

Issues and PRs on Forgejo preferred; GitHub PRs are mirrored collaboration.
Security-sensitive reports: open a private channel or a redacted public issue
linking the threat-model control that is affected.
