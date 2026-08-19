# Handoff — Kinocut 2026-08-19 closeout

Source of truth: Forgejo `git.kyanitelabs.tech/KyaniteLabs/kinocut`. GitHub is the mirror.

1. **Purpose** — Land the closeout receipt when CI is honest-green; do not reopen closed loops.
2. **Why it matters** — 1.15.0 is live on pip **and** kinocut.dev. PR #405 is the remaining desk merge; lint is the gate.
3. **Exact files** — `docs/status/NOW.md`, `docs/status/2026-08-19-ops-closeout.md`, `docs/HUMAN_GATES.md`, `docs/CI_RUNNER_TOPOLOGY.md`. Gitignored: `.omx/plans/BUG-SMELL-REGISTRY.md`.
4. **Exact commands** —
   ```bash
   git fetch origin github
   git rev-parse --short HEAD origin/master github/master
   curl -fsS https://kinocut.dev/llms.txt | sed -n '1,20p'
   fj status KyaniteLabs/kinocut "$(git rev-parse origin/docs/2026-08-19-ops-closeout)"
   fj api GET repos/KyaniteLabs/kinocut/actions/runners
   python3 -m pytest tests/test_public_claims.py tests/test_forgejo_workflows.py tests/test_ci_runner_contract.py -q
   ```
5. **Constraints** — Forgejo land first; never merge #405 while lint has no `lint-checkout`; never squash `v1.15.0` @ `64c5799`; never re-Enterprise `kinocut.dev`.
6. **Definition of done** — #405 merge-commit on Forgejo master; combined success **including** `lint-checkout`; live site still 1.15.0.
7. **Required evidence** — `fj status` on the merge SHA; runner list still documents colima vs nucbox; `https://kinocut.dev/llms.txt` says 1.15.0.
8. **What NOT to touch** — `.mimosa/`; perf-committee reports; PW dirty tree; Cloudflare Enterprise; `skills_agent/` unless named.
9. **Report format** — BLUF: result / blocker / owner word. Then: fixed / parked / needs-you.
10. **Mode** — Inspect-only unless the operator names `rerun 405` (only when `colima-ci-runner` is idle). Stop-and-ask: force-merge, nucbox label remap, timeout-minutes bump.

Cold-start: read item 3. Live fact: this repo’s only Actions runner is `colima-ci-runner` (id=15). `nucbox-ci` is not registered here. Busy-host = Colima capacity-2.
