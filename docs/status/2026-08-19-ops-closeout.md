# Kinocut ops closeout (2026-08-19)

**Verified:** 2026-08-19 (live oracles + Forgejo combined status)  
**Tip:** Forgejo `origin/master` = GitHub `master` = `5b1936e`  
**Published package:** **1.15.0** (PyPI, npm, MCP Registry latest, GitHub Release `v1.15.0` at tag SHA `64c5799`)

This is the current session receipt. It does not replace `docs/public_claims.json`.
`docs/status/` snapshots stay historical unless they name themselves current;
[NOW.md](NOW.md) is the one-page now-state.

## Verdict

Package identity, dual-host `master`, **kinocut.dev 1.15.0**, and Cloudflare DNS
are honest. The remaining desk residual is Forgejo PR **#405** (this closeout):
lint on the retrigger SHA died without `lint-checkout`. Do not merge it red.

## 1. Package and dual-host identity — done

| Surface | Live |
| --- | --- |
| PyPI `kinocut` | 1.15.0 (not yanked) |
| npm `kinocut` | 1.15.0 |
| MCP Registry `io.github.KyaniteLabs/kinocut` versions/latest | 1.15.0 |
| GitHub Release | `v1.15.0`, published 2026-08-19T16:36:10Z |
| Tags `v1.15.0` on `origin` and `github` | `64c5799` |
| `docs/public_claims.json` | `published_version` / `release_candidate_version` 1.15.0, date 2026-08-19 |
| Repo `llms.txt` | 1.15.0 (2026-08-19) |
| Forgejo combined status on `5b1936e` | **success** (lint-checkout, lint, tests 0–3, ffmpeg 6/7/8, test-slow, sync-master) |

Import path: PR **#402** (GitHub 1.15.0 cutover + leftover published-version honesty)
merged as a merge-commit. Do not squash `v1.15.0` at `64c5799`. Never `git push github`
as the land path.

## 2. Forgejo CI — done

Root cause of the invisible ~80s lint death (no `lint-checkout`):

1. `claims-live` ran on `light` and starved lint’s tiny apt/curl on the capacity-2 runner.
2. Runner cwd on the Mac virtiofs checkout (full volume) instead of VM-local disk.
3. A `trap` that POSTed `lint-checkout` via `curl` before `curl` was installed.

Fixes on tip:

- PR **#403** — `claims-live.yml` `runs-on: heavy` (`tests/test_forgejo_workflows.py`
  forbids `light`).
- PR **#404** — runner home `/mnt/lima-colima/forgejo-runner`; topology recorded.
- Lint job: tiny `apt-get install curl ca-certificates`, then curl POST, then git/python.

`timeout-minutes: 10` did **not** override the ~80s virtiofs kill. Do not “fix”
that class of hole by raising YAML timeouts.

### Recurrence on PR #405 (2026-08-19, still open)

Empty-commit retrigger `16a083e` (Actions run 929): lint **Failing after 1m21s**,
**no** `lint-checkout` context. Tests/ffmpeg `Has been skipped` (`needs: lint`).
Earlier head `62bbbfd` (run 928): `test (2)` **Failing after 1s** (job never
reached pytest). `origin/master` `5b1936e` remains combined **success**.

Operator hypothesis: **a box is busy** (named nucbox). Treat as *busy host /
capacity*, not as a proven nucbox queue:

| Check (live 2026-08-19) | Result |
| --- | --- |
| Runners registered on `KyaniteLabs/kinocut` | **one**: `colima-ci-runner` (id=15, forgejo-runner v13.0.0) |
| Labels on that runner | `heavy`, `light`, `default`, `arm64-heavy` (all `docker://ubuntu:24.04`) |
| Runner status at this probe | `idle` |
| `nucbox-ci` on this repo’s runner list | **absent** (2026-07-10 topology mention is historical) |

So Kinocut jobs do not wait on a separate nucbox runner unless an admin attaches
one. Contention that *does* match the ~80s / no-`lint-checkout` signature is
**Colima capacity-2**: lint (`light`) and pytest/ffmpeg (`arm64-heavy`) share the
same VM. A busy **other** Forgejo repo on nucbox would not show up here and
would not pick these labels.

Do not force-merge. Do not raise `timeout-minutes`. Rerun when `colima-ci-runner`
is idle and the Mac volume is not full. Forgejo on this instance has **no**
job-rerun API (404); retrigger is an empty commit or a new push.

Contract: [CI_RUNNER_TOPOLOGY.md](../CI_RUNNER_TOPOLOGY.md).

## 3. Public site — done (1.15.0 live)

`https://kinocut.dev/` (re-verified after deploy):

- `/llms.txt`: Last-updated **2026-08-19**, latest published **1.15.0**
- Homepage `softwareVersion` / edit-bay sub: **1.15.0**
- Remaining `1.14.1` strings on the homepage are historical (“same 196/167
  surface as 1.14.1”), not current-claim chips
- Agent card: HTTP 200
- Primary-surface gate passed against the live URL

Land path: kinocut-site Forgejo PR **#19** merge-commit `11e0d2c`, GitHub mirror
FF to the same SHA, `npx netlify deploy --prod --dir .`. Dual-host site tips
match. Bump script must pass old version **1.14.1** as argv3 (default is 1.8.0).

## 4. Cloudflare DNS for kinocut.dev — done, stay Free

Live DNS (2026-08-19):

| Record | Value |
| --- | --- |
| NS | `frank.ns.cloudflare.com` / `raphaela.ns.cloudflare.com` |
| Apex A/AAAA | Cloudflare proxy (`104.18.10.78` / `104.18.11.78`, `2606:4700::…`) |
| `www` | Same Cloudflare proxy addresses |
| `skills.kinocut.dev` | NXDOMAIN (not created) |

Registrar was Hostinger (`lunar`/`solar.dns-parking.com`) before the NS cutover.
The zone was briefly attached as **Enterprise**, then taken off at operator
direction. **Leave `kinocut.dev` on Free Website.** Enterprise slots are a
separate quota from Startup credits; DNS and a named tunnel do not need
Enterprise.

Do not:

- Re-select Enterprise for this zone unless the operator names that zone.
- Treat Wrangler OAuth as zone-admin (it cannot create zones or write DNS).
- Point the apex away from the Netlify origin as a side effect of tunnel work.

Kinocut is not flagship. See the local Cloudflare Startups skill and
non-flagship rails (not copied here).

## 5. Skills-agent plan — gated

Plan: PuenteWorks
`internal/plans/ralplan-kinocut-a2a-skills-agent-20260819.md`.

| Gate | State |
| --- | --- |
| 0a zone on Cloudflare | **GO** (NS live above) |
| 0b China-side DNS + card GET + POST + >100s SSE | **not run** |
| `skills.kinocut.dev` DNS | **not created** |
| `skills_agent/` scaffold in this repo | **not started** |

Do not scaffold until 0b passes **and** the operator names the scaffold.
A free `trycloudflare.com` quick tunnel is not production.

## 6. PuenteWorks A2A `message/send` — live, git unpushed

Live `POST https://puenteworks.com/a2a/v1` (2026-08-19):

- `message/send` → 200 JSON-RPC result
- `SendMessage` → 200 JSON-RPC result
- `message/stream` → `-32601` Method not found (card says streaming false)

Local PuenteWorks `main` is **17 commits ahead of `origin/main`** (includes
`506f99f fix(a2a): accept message/send on /a2a/v1`) plus unrelated dirty
internal files. **Do not push that tree from this desk.** Owner pushes PW
when ready. Prod already has the one-line dual-method fix.

## 7. Human residuals (unchanged product gates)

From [HUMAN_GATES.md](../HUMAN_GATES.md), still human:

- Renovate host tokens
- Directory listings #88 (Awesome MCP Servers already merged)
- Launch moments #90
- First-10 **closed** (obsolete)

Windows credit loop:

- Code for portable locking is on master / pip 1.15.0.
- GitHub PR **#446** is CLOSED unmerged (`mergedAt` null); equivalent landed
  as Simon’s commit.
- Issue **#445** **CLOSED** 2026-08-19 (`state_reason=completed`) with credit
  to [@gerardoscaglia-creator](https://github.com/gerardoscaglia-creator).

## 8. Local leftovers — do not commit

| Path | Why |
| --- | --- |
| `.mimosa/` | agent scratch — still do not commit |
| `docs/status/perf-committee/` | parked as inspect receipts; do not re-implement the 360 split (already `render_window_single_pass` in 1.14.0) |
| `.omx/` / `.omc/` | gitignored plans and the bug-smell registry |

Installed `$kinocut` skill on this host was resynced from `skills/kinocut/SKILL.md`
(2026-08-19). Not a repo commit.

## 9. Agent-system upgrades this closeout

Repeatable failures this campaign produced:

1. New Cloudflare zones selected **Enterprise** at add-site (quota burn, operator
   reversal). Guardrail: Cloudflare Startups skill — new zones default **Free**.
2. Installed `$kinocut` skill drifted from the repo skill after honesty work.
3. Smell registry left OPEN after the package actually published.

Those are recorded in `.omx/plans/BUG-SMELL-REGISTRY.md` (gitignored) and in
the Cloudflare skill (owning source). This receipt does not copy that policy.

## Explicitly not done

- Merge of PR **#405** (lint red; no `lint-checkout` on retrigger)
- `skills.kinocut.dev` record or processor
- China 0b probe
- Push of PuenteWorks’ 17 local commits
- GitHub comment/close on #445 — **done** 2026-08-19
- Re-Enterprise of any zone
- Committing `.mimosa/`
- Fixing the pre-existing local `test_mcpb_launcher_is_compatible_with_the_declared_node_floor` failure

## Owner words (copy-paste)

| Phrase | Effect |
| --- | --- |
| `rerun 405` | empty-commit or push when `colima-ci-runner` is idle; merge only if lint-checkout exists |
| `run 0b` | China reachability probe only; still no scaffold |
| `scaffold skills-agent` | start `skills_agent/` after 0b GO |
| `push PW` | push PuenteWorks `main` (inspect dirty tree first) |
| `close 445` | **done** 2026-08-19 — GH issue closed completed |
