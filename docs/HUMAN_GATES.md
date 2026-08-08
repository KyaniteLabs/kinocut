# Human / ops residual (updated 2026-08-08)

Agent-closable prep is on tip. Live outcomes below still need a human operator.

| Former issue | Agent deliverable | Still human |
| --- | --- | --- |
| #3 Renovate dashboard | `.github/dependabot.yml` + `.renovaterc.json` + note that Forgejo Renovate needs `GITHUB_COM_TOKEN`/hostRules | Enable token / Renovate app on host (requires Forgejo admin) |
| #88 Directory submissions | `docs/DIRECTORY_REBRAND_STATUS.md` + `docs/status/DIRECTORY_SUBMISSION_OPS.md` | Awesome MCP Servers PR **merged** (2026-08-08). MCP.so, Docker MCP, Agent-CoreX, Protodex still pending external review |
| #90 Launch moments | `docs/status/LAUNCH_MOMENTS.md` drafts + checklists | Approve & publish posts/clips |
| #92 First-10 users | `docs/status/USER_PROGRAM_RUNBOOK.md` | Recruit, run, log 10 real first-runs |

## Forgejo CI runner

CI workflow (`ci.yml`) routes all jobs to the `heavy` label. Recent runs show
intermittent success/failure — the `heavy` runner is available but occasionally
at capacity. The `light` label is unavailable. Fixing runner allocation requires
Forgejo admin access (`read:admin`) to verify runner placement and capacity.
The repo token does not have this permission.

Do not invent completed users, published launch metrics, or third-party directory approvals.
