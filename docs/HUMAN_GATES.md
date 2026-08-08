# Human / ops residual (updated 2026-08-08)

Agent-closable prep is on tip. Live outcomes below still need a human operator.

| Former issue | Agent deliverable | Still human |
| --- | --- | --- |
| #3 Renovate dashboard | `.github/dependabot.yml` + `.renovaterc.json` + note that Forgejo Renovate needs `GITHUB_COM_TOKEN`/hostRules | Enable token / Renovate app on host (requires Forgejo admin) |
| #88 Directory submissions | `docs/DIRECTORY_REBRAND_STATUS.md` + `docs/status/DIRECTORY_SUBMISSION_OPS.md` | Awesome MCP Servers PR **merged** (2026-08-08). MCP.so, Docker MCP, Agent-CoreX, Protodex still pending external review |
| #90 Launch moments | `docs/status/LAUNCH_MOMENTS.md` drafts + checklists | Approve & publish posts/clips |
| #92 First-10 users | `docs/status/USER_PROGRAM_RUNBOOK.md` | Recruit, run, log 10 real first-runs |

## Forgejo CI runner

CI runner (`colima-ci-runner`, id=15) runs inside the Colima VM via
forgejo-runner v13.0.0 with systemd. Steps execute and some runs pass.
Remaining CI step failures need web UI log analysis at
`https://git.kyanitelabs.tech/KyaniteLabs/kinocut/actions` — the API
does not expose step-level output. Likely causes: `${{ secrets.GITHUB_TOKEN }}`
not injected on some jobs, or test-specific failures inside containers.

## Adversarial audit residuals

From gpt-5.6-sol audit (2026-08-08). 9 of 11 security findings fixed
(PR #341–#344). Two remain:

| ID | Severity | File | Issue |
|---|---|---|---|
| C1 | CRITICAL | `ai_engine/download.py` | SSRF — HTTP/yt-dlp requests reach destination before IP validation |
| M1 | MEDIUM | `hyperframes_engine.py` | Detached preview processes leak servers/ports |

C1 needs an IP-validation transport (pinned-address). M1 needs a preview
lifecycle refactor. Both are follow-up PRs.

Do not invent completed users, published launch metrics, or third-party directory approvals.
