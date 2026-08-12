# Human / ops residual (updated 2026-08-12)

Agent-closable prep is on tip. Live outcomes below still need a human operator.
Do **not** invent completions for #3 / #88 / #90 / #92. Residual portfolio authority:
[`docs/status/2026-08-12-residual-maturity-matrix.md`](status/2026-08-12-residual-maturity-matrix.md)
· [L1 truth pass](status/2026-08-12-l1-truth-pass.md).

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
(PR #341–#344). **C1/M1 claim-audit (2026-08-12, L0):** closed as **verify-only pass**
on tip — pin-before-connect + peer validation present; preview registry +
`stop_preview`/`atexit` present; SSRF/preview tests green. See
`.omx/state/l0-claim-audit.md`. Reopen only with a **failing case**.

| ID | Severity | File | Status |
|---|---|---|---|
| C1 | CRITICAL | `ai_engine/download.py` | **Claim-audit pass** (2026-08-12) — do not rebuild without fail |
| M1 | MEDIUM | `hyperframes_engine.py` | **Claim-audit pass** (2026-08-12) — do not redesign without fail |

Do not invent completed users, published launch metrics, or third-party directory approvals.

## Deferred portfolio rows

See [`docs/status/DEFERRED.md`](status/DEFERRED.md) for agent-vs-human residual IDs. Human rows must not be agent-closed.
