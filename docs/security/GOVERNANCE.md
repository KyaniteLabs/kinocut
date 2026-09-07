# Governance & stewardship (GOV.1)

**Status:** living doc · **Date:** 2026-09-06
**Current authority:** GitHub primary; Forgejo downstream mirror
**Proposal and transition context:** [GitHub #499](https://github.com/KyaniteLabs/kinocut/issues/499)
**Original GOV.1 record:** Forgejo #91

## Why this exists

Single-maintainer open-source tools attract a fair bear case: bus factor, silent
abandonment, and opaque release decisions. Kinocut counters that with **visible
stewardship** — not performance theater.

## What is public

| Surface | Where |
| --- | --- |
| Source of truth | GitHub [`KyaniteLabs/kinocut`](https://github.com/KyaniteLabs/kinocut): code, issues, PRs, CI, tags, and releases |
| Downstream mirror | Forgejo `KyaniteLabs/kinocut` (`git.kyanitelabs.tech`); automation-only updates to `master` |
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

1. **No silent public-face hollowing** — the dual-host README/S+ floor applies, with GitHub as Kinocut's authority host.
2. **No invented human gates** — listening/user programs stay human-owned.
3. **Release claims match packages** — `public_claims.json` is the lockstep file.
4. **Security findings** route through the threat model and fail-closed defaults.

## How to contribute

Open issues, discussions, and PRs on GitHub. Do not land normal changes independently on Forgejo; its GitHub-to-Forgejo sync mechanism is pending live-gate verification.
Security-sensitive reports: open a private channel or a redacted public issue
linking the threat-model control that is affected.
