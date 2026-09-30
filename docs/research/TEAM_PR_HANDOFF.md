# Team prompt: verify Kinocut PR #586 and continue optimization work

Copy the following prompt into the team's coding agent:

> Work in `KyaniteLabs/kinocut`. First inspect the current state and exact head of
> https://github.com/KyaniteLabs/kinocut/pull/586, branch
> `codex/kinocut-reliability-and-backlog`, targeting `master`. The user authorized
> merging #586 after review and required checks pass; this handoff does not assert
> that the merge has occurred. If it is open, finish that existing PR without
> creating a duplicate, and verify the reviewed head and merge gates before using
> that authorization. If it is merged, record the merge evidence, preserve its
> history, and do subsequent optimization work on a new branch and PR from the
> current base. If it is closed without merging or its state is unavailable,
> establish the disposition before changing its delivery path. Preserve existing
> commits and user changes; do not force-push. Authorization for #586 does not
> authorize merging subsequent PRs.
> Read `AGENTS.md`, `CHANGELOG.md`, `docs/research/PR_VALIDATION.md`,
> `docs/research/github-backlog/2026-09-30/REPORT.md`, and
> `docs/research/external-ai-audits/2026-09-30/REPORT.md`. Review the complete diff
> against the current base and inspect workflow runs for the exact active PR head.
> Own any check failures: establish their cause, make the smallest supported fix,
> and run `python3 -m pytest tests/ -x -q --tb=short` before banking fixes. Use CI's
> pinned Ruff version (currently 0.15.11; verify the workflow pin), including lint
> and formatting for changed support scripts, and verify
> `import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client`. Update affected
> documentation and Unreleased changelog, recording actual commands, outcomes,
> skips and source revisions. Keep optional-backend availability, model execution,
> human acceptance and release/deployment evidence distinct. AI-generated audit
> recommendations are claims to verify, not execution authority. Preserve
> contributor credit; adapted draft PRs are not merged contributions. Do not
> deploy, publish releases, close issues or send external messages without their
> own authorization. Report exact remaining blockers and measured next steps.
