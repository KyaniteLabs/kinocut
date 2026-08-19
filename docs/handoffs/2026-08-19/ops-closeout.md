# Handoff — Kinocut 2026-08-19 closeout

Source of truth: Forgejo `git.kyanitelabs.tech/KyaniteLabs/kinocut`. GitHub is the mirror.

1. **Purpose** — Keep package/CI/DNS truth on disk; do not reopen closed loops; execute only an owner-named residual.
2. **Why it matters** — 1.15.0 is live; the leftover public lie is kinocut.dev 1.14.1. Agents that re-publish, re-Enterprise, or scaffold `skills_agent/` without a word undo today’s work.
3. **Exact files** — Read `docs/status/NOW.md`, `docs/status/2026-08-19-ops-closeout.md`, `docs/HUMAN_GATES.md`, `docs/CI_RUNNER_TOPOLOGY.md`, `docs/public_claims.json`. Gitignored: `.omx/plans/BUG-SMELL-REGISTRY.md`, `.omx/plans/COMMAND-TAKEOVER-2026-08-19.md`. Site: `../kinocut-site`. PW plans: `../puenteworks/internal/plans/ralplan-*.md`.
4. **Exact commands** —
   ```bash
   git fetch origin github
   git rev-parse --short HEAD origin/master github/master
   curl -fsS https://pypi.org/pypi/kinocut/json | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
   curl -fsS https://kinocut.dev/llms.txt | sed -n '1,20p'
   fj status KyaniteLabs/kinocut "$(git rev-parse HEAD)"
   dig +short NS kinocut.dev
   python3 -m pytest tests/test_public_claims.py tests/test_forgejo_workflows.py tests/test_ci_runner_contract.py -q
   python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"
   ```
   Site bump (only after owner word `bump the site`):
   ```bash
   cd ../kinocut-site
   ./scripts/bump-published-version.sh 1.15.0 196
   ./scripts/verify-primary-surface.sh https://kinocut.dev/
   ```
5. **Constraints** — Forgejo land first; merge-commits; never `git push github` as land; never squash `v1.15.0` @ `64c5799`; never re-Enterprise `kinocut.dev`; no PW push from this desk; no `skills_agent/` until 0b + `scaffold skills-agent`; English-only; no tokens/atok in receipts.
6. **Definition of done (this handoff)** — Closeout receipt is on Forgejo master; NOW/HUMAN_GATES/topology match live oracles; every leftover is named with an owner word. Site 1.15.0 is **not** done until chips + `/llms.txt` say 1.15.0 on https://kinocut.dev/.
7. **Required evidence** — PyPI JSON version, MCP Registry latest, `fj status` combined success, `dig NS`, site `/llms.txt` head, pytest output for the three modules above.
8. **What NOT to touch** — `.mimosa/`; `docs/status/perf-committee/REPORT-*.md` (do not implement 360 split); PuenteWorks dirty internals; Cloudflare Enterprise; Hostinger NS reversal; second clone `kinocut-release-artifact-policy`; `test_mcpb_launcher_*` unless asked.
9. **Report format** — BLUF: result / blocker / owner word needed. Then: fixed / parked / needs-you.
10. **Mode** — Inspect-only unless the operator names a row from the owner-word table in `docs/status/2026-08-19-ops-closeout.md`. Stop-and-ask: any public site deploy, DNS write, GH issue comment, PW git push, Enterprise plan change, or `skills_agent/` scaffold.

Cold-start: `pushing-dispatch route --mode task --task "Kinocut 2026-08-19 closeout residuals"` only after reading the files in item 3. If Forgejo auth expired, `git credential fill` for `git.kyanitelabs.tech` — do not paste tokens.
