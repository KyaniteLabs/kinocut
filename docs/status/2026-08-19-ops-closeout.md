# Kinocut ops closeout (2026-08-19)

**Verified:** 2026-08-19 (live oracles + Forgejo combined status)  
**Tip:** Forgejo `origin/master` = GitHub `master` = `5b1936e`  
**Published package:** **1.15.0** (PyPI, npm, MCP Registry latest, GitHub Release `v1.15.0` at tag SHA `64c5799`)

This is the current session receipt. It does not replace `docs/public_claims.json`.
`docs/status/` snapshots stay historical unless they name themselves current;
[NOW.md](NOW.md) is the one-page now-state.

## Verdict

Package identity, dual-host tip, and the Forgejo merge gate are honest and green.
The remaining **public lie** is the product site: `https://kinocut.dev/` still
stamps **1.14.1**. Everything else below is either done, parked with an owner
word, or a local/gitignored leftover that must not be committed.

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

Contract: [CI_RUNNER_TOPOLOGY.md](../CI_RUNNER_TOPOLOGY.md).

## 3. Public site residual — owner word (honesty leftover)

Live `https://kinocut.dev/` (2026-08-19):

- Homepage chips: **1.14.1** (no 1.15.0 string).
- `/llms.txt`: Last-updated 2026-08-13, latest published **1.14.1**.
- `/.well-known/agent-card.json`: HTTP 200.
- HTML is still served from Netlify (`cache-status: Netlify Edge`) in front of
  Cloudflare DNS/proxy (`server: cloudflare`).

Sibling repo `workspaces/kinocut-site` tip is still the 1.14.1 cutover
(`0c18b31` / later Ko-fi footer). Forgejo is origin; GitHub is the mirror.

Exact next command (do not run until the operator names the site bump):

```bash
cd ../kinocut-site
./scripts/bump-published-version.sh 1.15.0 196
./scripts/verify-primary-surface.sh https://kinocut.dev/
```

Land that PR on **Forgejo first**, then confirm Netlify. Ritual reminder:
[RELEASE_1.8_CHECKLIST.md](../RELEASE_1.8_CHECKLIST.md) §6 (same script, later version).

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
  as Simon’s commit. Issue **#445** is still **OPEN**. Closing #445 with
  credit is an outbound GitHub action — owner word, this desk does not comment.

## 8. Local leftovers — do not commit

| Path | Why |
| --- | --- |
| `.mimosa/` | agent scratch |
| `docs/status/perf-committee/REPORT-*.md` | untracked inspect leftovers; do not re-implement 360 split (already single-pass in 1.14.0). Smell KC-005. |
| `.omx/` / `.omc/` | gitignored plans and the bug-smell registry |

Installed `$kinocut` skill on this host was the 2026-07-13 copy; the repo skill
is 2026-08-13 (360 default path, QC-80, shorts/sound). Resync is a local copy
from `skills/kinocut/SKILL.md`, not a repo commit.

## 9. Agent-system upgrades this closeout

Repeatable failures this campaign produced:

1. New Cloudflare zones selected **Enterprise** at add-site (quota burn, operator
   reversal). Guardrail: Cloudflare Startups skill — new zones default **Free**.
2. Installed `$kinocut` skill drifted from the repo skill after honesty work.
3. Smell registry left OPEN after the package actually published.

Those are recorded in `.omx/plans/BUG-SMELL-REGISTRY.md` (gitignored) and in
the Cloudflare skill (owning source). This receipt does not copy that policy.

## Explicitly not done

- kinocut-site 1.15.0 bump / Netlify deploy
- `skills.kinocut.dev` record or processor
- China 0b probe
- Push of PuenteWorks’ 17 local commits
- GitHub comment/close on #445
- Re-Enterprise of any zone
- Committing perf-committee reports or `.mimosa/`
- Fixing the pre-existing local `test_mcpb_launcher_is_compatible_with_the_declared_node_floor` failure

## Owner words (copy-paste)

| Phrase | Effect |
| --- | --- |
| `bump the site` | kinocut-site 1.15.0 ritual, Forgejo first |
| `run 0b` | China reachability probe only; still no scaffold |
| `scaffold skills-agent` | start `skills_agent/` after 0b GO |
| `push PW` | push PuenteWorks `main` (inspect dirty tree first) |
| `close 445` | outbound GitHub close/credit on the Windows issue |
