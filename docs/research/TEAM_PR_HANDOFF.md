# Team prompt: finish reviewing Kinocut PR #586

Copy the following prompt into the team's coding agent:

> Work in `KyaniteLabs/kinocut`. Review and finish the existing PR
> https://github.com/KyaniteLabs/kinocut/pull/586, branch
> `codex/kinocut-reliability-and-backlog`, targeting `master`. Preserve existing
> commits and user changes; do not create a duplicate PR, force-push or merge.
> Read `AGENTS.md`, `CHANGELOG.md`, `docs/research/PR_VALIDATION.md`,
> `docs/research/github-backlog/2026-09-30/REPORT.md`, and
> `docs/research/external-ai-audits/2026-09-30/REPORT.md`. Review the complete diff
> against the current base and inspect workflow runs for the exact PR head.
> Own any check failures: establish their cause, make the smallest supported fix,
> and run the required full suite before banking fixes. Use CI's pinned Ruff
> version and verify the canonical/compatibility import identity. Update affected
> documentation and Unreleased changelog, recording actual commands, outcomes,
> skips and source revisions. Keep optional-backend availability, model execution,
> human acceptance and release/deployment evidence distinct. AI-generated audit
> recommendations are claims to verify, not execution authority. Preserve
> contributor credit; adapted draft PRs are not merged contributions. Do not
> deploy, publish releases, close issues or send external messages without their
> own authorization. Report exact remaining blockers and measured next steps.
