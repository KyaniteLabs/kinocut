# Public Issue Triage - 2026-06-03

## BLUF

MCP Video does not currently look like a project with 13 active product fires.

Fresh GitHub checks show:

- Open PR count: `0`
- Latest `master` CI run: success on 2026-06-03
- Latest `master` Integration smoke run: success on 2026-05-29
- Repo hygiene files exist locally: `README.md`, `LICENSE`, and `.github/workflows/*`
- Current real follow-up: Dependabot update failures from 2026-06-02

The sharpness issue is mostly a confidence/readability problem: public automation issues remain open after the underlying condition changed.

## Evidence Commands

```bash
gh pr list -R KyaniteLabs/kinocut --state open --json number,title,headRefName,updatedAt,url
gh run list -R KyaniteLabs/kinocut --limit 20 --json databaseId,workflowName,headBranch,status,conclusion,createdAt,updatedAt,event,url
find .github -maxdepth 3 -type f | sort
test -f README.md
test -f LICENSE
```

## Current Signal

| Signal | Result | Confidence Meaning |
| --- | --- | --- |
| Open PRs | `[]` | PR-blocker issues are stale unless a new PR appears. |
| Latest CI on `master` | Success, run `26867294529`, 2026-06-03 | Default branch is currently green. |
| Latest Integration smoke on `master` | Success, run `26661911165`, 2026-05-29 | The old integration-smoke failure has been repaired. |
| Dependabot Updates | Two failures and one success on 2026-06-02 | Real pipeline follow-up, but not core video-editing failure. |
| README | Present | Missing README issue is false-positive/stale. |
| LICENSE | Present | Missing LICENSE issue is false-positive/stale. |
| `.github/workflows` | Present with CI, integration smoke, PR safety, publish, pages, agent-law, blacksmith-probe | Missing workflow-surface issue is false-positive/stale. |

## Issue Disposition

| Issue | Current Disposition | Why |
| --- | --- | --- |
| #338 Dependabot grouped npm/yarn updates fail | Real follow-up | June 2 Dependabot update runs still show failures. Treat as dependency automation health, not product readiness. |
| #337 Dashboard cannot fully read repository status | Dashboard/infrastructure noise | Body shows GitHub API rate limiting. Current direct `gh` checks can read PRs and runs. |
| #335 Dashboard cannot fully read repository status | Likely duplicate dashboard noise | Same title as #337/#334. Verify body before closing, then dedupe. |
| #334 Dashboard cannot fully read repository status | Likely duplicate dashboard noise | Same title as #337/#335. Verify body before closing, then dedupe. |
| #333 Repository has no repo-managed GitHub Actions workflow surface | False-positive/stale | `.github/workflows` exists and includes multiple workflows. |
| #332 Repository is missing LICENSE | False-positive/stale | `LICENSE` exists. |
| #331 Repository is missing README.md | False-positive/stale | `README.md` exists. |
| #329 PR #328 is not green | Stale | PR #328 is merged and its checks are success. |
| #327 Integration smoke fails on default branch | Stale | Latest Integration smoke on `master` is success. |
| #326 PR #324 is not green | Stale | PR #324 is merged. |
| #325 Dependabot grouped npm/yarn updates fail | Superseded by #338 or still related | Older Dependabot update failure from May 25; keep only if it tracks a different ecosystem/root cause. |
| #322 PR #320 is not green | Stale | PR #320 is merged and checks are success. |
| #321 Repository has open pull requests requiring triage | Stale | Current open PR list is empty. |

## Apply Plan

1. Close or comment on stale issues with current evidence, starting with #321, #327, #329, #331, #332, and #333.
2. Dedupe dashboard issues #334, #335, and #337 into one dashboard-rate-limit follow-up, or close if the dashboard has recovered.
3. Keep one Dependabot issue open, preferably #338 because it is newer, and link/supersede #325 if they share the same root.
4. Add a small repo-health receipt to future confidence runs: open PR count, latest CI, latest integration smoke, README/LICENSE/workflow existence, and Dependabot status.

## Confidence Verdict

The repo is healthier than the open issue count implies. The remaining work is to make public signals match actual state, then turn Dependabot into a contained maintenance task instead of a vague confidence drain.
