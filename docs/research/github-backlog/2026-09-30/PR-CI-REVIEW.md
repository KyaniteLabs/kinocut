# Public exact-head PR CI review

Reviewed 2026-09-30 using certificate-verified public GitHub HTTPS HTML. REST/GraphQL access remains unavailable in the parent review. No approval, dispatch, settings, credentials, or branch mutation performed.

The selected commit full SHA in each PR checks page matches the refreshed inventory. Embedded `pullRequestsChecksRoute.Main` HTML exposes individual job aria-label statuses, so evidence below comes from reported jobs, not an empty API rollup.

## PR #579

- Draft head: `f1891a9a1c9e6b34c64fb0e232a48f25b33edecd`.
- Checks page: https://github.com/KyaniteLabs/kinocut/pull/579/checks.
- 13 visible jobs reported succeeded; no other job state found in this selected-head HTML.
- Integration smoke: 5 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36320033523.
- Staged MCPB: 6 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36320033535.
- PR safety: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36320033558.
- Agent Law: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36320033712.
- This establishes visible checks attached to the selected PR head, not that master CI, merge eligibility, every required branch-protection check, or an eventual integration commit is green.

## PR #577

- Draft head: `8986a05c74aca4b8192823f293527aeb551e5683`.
- Checks page: https://github.com/KyaniteLabs/kinocut/pull/577/checks.
- 13 visible jobs reported succeeded; no other job state found in this selected-head HTML.
- Integration smoke: 5 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36319638601.
- Staged MCPB: 6 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36319638605.
- PR safety: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36319638637.
- Agent Law: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36319638661.
- This establishes visible checks attached to the selected PR head, not that master CI, merge eligibility, every required branch-protection check, or an eventual integration commit is green.

## PR #575

- Draft head: `ca896570f7da9b1a3b042081eceae64d9a9593fb`.
- Checks page: https://github.com/KyaniteLabs/kinocut/pull/575/checks.
- Page explicitly reports “Workflow runs completed with no jobs.” It provides no job evidence and no approval-request message. Successful CI coverage is unverified; neither absent workflows nor an approval requirement can be inferred.

## PR #573

- Draft head: `c64aa001b2bd9215390addf81fe2980b114a1600`.
- Checks page: https://github.com/KyaniteLabs/kinocut/pull/573/checks.
- Page explicitly reports “Workflow runs completed with no jobs.” It provides no job evidence and no approval-request message. Successful CI coverage is unverified; neither absent workflows nor an approval requirement can be inferred.

## PR #567

- Draft head: `684f8a632239884235e8fb80d3218f9fefe33d90`.
- Checks page: https://github.com/KyaniteLabs/kinocut/pull/567/checks.
- 13 visible jobs reported succeeded; no other job state found in this selected-head HTML.
- Staged MCPB: 6 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36219847146.
- Integration smoke: 5 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36219847149.
- Agent Law: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36219847155.
- PR safety: 1 succeeded jobs; https://github.com/KyaniteLabs/kinocut/actions/runs/36219847174.
- This establishes visible checks attached to the selected PR head, not that master CI, merge eligibility, every required branch-protection check, or an eventual integration commit is green.

## Workflow definitions inspected in checkout

- `ci.yml` is push-to-master or workflow_dispatch only. Its full master suite does not automatically run merely because these draft PRs have 13 successful PR checks.
- `pr-safety.yml` is pull_request-to-master, ubuntu-latest, checkout credentials disabled; code changes run hosted Ruff and pytest not-slow. No explicit draft guard, pull_request_target trigger, secret injection, or workflow-approval job is present.
- `integration-smoke.yml` runs on code-related pull_request paths, push and dispatch; five jobs use ubuntu-24.04.
- `mcpb.yml` runs pull_request-to-master, push, dispatch, contents read permission and disabled persisted checkout credentials; clean runtime uses hosted Linux/macOS/Windows matrix plus optional discovery and aggregate.
- `agent-law.yml` runs pull_request/merge_group/dispatch with contents read. Runner selection is vars.RUNNER_LABEL or ubuntu-latest; public repository-variable values and external approval settings are not visible here.
- No approval-needed message was found in any of the five checked public checks pages. Therefore no speculative approval was attempted. Account policy or external gate status needs authenticated visibility if further diagnosis is required.
- Actions index requests with head_sha query returned unrelated runs too; they were discarded as exact-head evidence. Missing entries in those results were not interpreted as missing CI.

Downloaded evidence: /tmp/kinocut-pr-N-checks.html and parsed /tmp/kinocut-pr-N-checks-payload.json, with N=579,577,575,573,567. Local modifications and root integration tests remain a separate validation surface.
