# Human / ops residual (updated 2026-08-12)

Agent-closable prep is on tip. Live outcomes below still need a human operator
where noted. Residual portfolio authority:
[`docs/status/2026-08-12-residual-maturity-matrix.md`](status/2026-08-12-residual-maturity-matrix.md)
· [L1 truth pass](status/2026-08-12-l1-truth-pass.md)
· [DEFERRED](status/DEFERRED.md).

| Former issue | Agent deliverable | Status |
| --- | --- | --- |
| #3 Renovate dashboard | `.github/dependabot.yml` + `.renovaterc.json` + `.forgejo/workflows/renovate.yml` + runbook [`docs/ops/RENOVATE_HOST_TOKEN.md`](ops/RENOVATE_HOST_TOKEN.md) | **Still human/ops** — set `RENOVATE_TOKEN` + `MIRROR_GITHUB_TOKEN` on Forgejo; agent runbook complete |
| #88 Directory submissions | `docs/DIRECTORY_REBRAND_STATUS.md` + `docs/status/DIRECTORY_SUBMISSION_OPS.md` | Awesome MCP Servers PR **merged** (2026-08-08). MCP.so, Docker MCP, Agent-CoreX, Protodex still pending external review |
| #90 Launch moments | `docs/status/LAUNCH_MOMENTS.md` drafts + checklists | Approve & publish posts/clips (marketing ops, not product maturity) |
| #92 First-10 users | `docs/status/USER_PROGRAM_RUNBOOK.md` | **CLOSED as obsolete (2026-08-12)** — adoption already past a “first 10” gate (see live signals below) |

## Live adoption signals (re-verified 2026-08-12)

| Signal | Value | Source |
| --- | --- | --- |
| GitHub stars | **107** | `gh api repos/KyaniteLabs/kinocut` |
| GitHub forks | **25** | same |
| PyPI downloads (last day) | **608** | pypistats / pypi.org API |
| PyPI downloads (last week) | **6,715** | same |
| PyPI downloads (last month) | **23,034** | same |
| Published package | **1.14.1** | PyPI |

Downloads are not a unique-user census, but stars + forks + multi‑k weekly installs
make “recruit first 10 users” an obsolete product gate. Do **not** re-open #92 as
incomplete pipeline work.

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

Do not invent third-party directory approvals. Do not re-open #92 as a missing
“first 10” product gate.

## Deferred portfolio rows

See [`docs/status/DEFERRED.md`](status/DEFERRED.md). Growth/marketing rows are
optional ops, not incomplete product phases.
