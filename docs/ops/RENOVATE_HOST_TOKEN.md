# Renovate host token (#3) — superseded for Kinocut

**Status:** superseded 2026-09-06 by Kinocut's GitHub-primary policy
**Proposal and transition context:** [#499](https://github.com/KyaniteLabs/kinocut/issues/499)
**Related:** `docs/HUMAN_GATES.md` · `.renovaterc.json` · `.github/dependabot.yml`

## Current direction

GitHub is the canonical host for Kinocut dependency PRs. Use
`.github/dependabot.yml` and review dependency updates through the normal GitHub
PR and CI path. Forgejo is a downstream mirror; a scheduled Renovate job there
must not create or merge an independent normal change.

The [GitHub-to-Forgejo sync implementation](../../.github/workflows/sync-forgejo.yml)
is present. Bootstrap, activation, and live verification remain pending. Until
those gates pass, report drift and do not restore the removed Forgejo Renovate
workflow as a workaround.

## Repository artifacts during cutover

| Artifact | Role |
| --- | --- |
| `.github/dependabot.yml` | Canonical GitHub dependency PRs |
| Former path: `.forgejo/workflows/renovate.yml` | Removed Forgejo-primary job, retained here as historical context |
| `.renovaterc.json` | Legacy configuration; its Forgejo workflow has been removed |

## Superseded setup

Earlier versions of this runbook directed an operator to provision
`RENOVATE_TOKEN` and `MIRROR_GITHUB_TOKEN` on Forgejo, dispatch the scheduled
Renovate workflow, and accept Forgejo dependency PRs. Those directions belonged
to the former Forgejo-primary topology and must not be executed for Kinocut.

Do not mint, copy, rotate, or install either credential for this superseded path.
Do not add `hostRules` carrying a GitHub token to `.renovaterc.json`. Existing
credentials, if any, are an administrator-owned inventory and revocation matter;
this document makes no claim about their live state.

## Cutover acceptance

- [ ] A GitHub Dependabot PR runs the normal exact-head GitHub CI and review gates.
- [ ] No scheduled or manual Forgejo Renovate job creates an independent PR.
- [ ] The separate GitHub-to-Forgejo sync gate proves the accepted GitHub commit reaches Forgejo unchanged.
- [ ] Documentation no longer directs maintainers or contributors to land dependency changes on Forgejo.

These checks describe the desired state; they do not claim the GitHub-to-Forgejo downstream sync gate
or any credential cleanup has completed.
