# Renovate host token (#3)

**Status:** agent-prep complete · live enablement is **human/Forgejo admin**  
**Related:** `docs/HUMAN_GATES.md` · `.renovaterc.json` · `.forgejo/workflows/renovate.yml` · `.github/dependabot.yml`

## What is already in-repo

| Artifact | Role |
| --- | --- |
| `.renovaterc.json` | Recommended Renovate config (`config:recommended`, automerge on) |
| `.forgejo/workflows/renovate.yml` | Scheduled Renovate job (every 6h + `workflow_dispatch`) on Forgejo |
| `.github/dependabot.yml` | GitHub-side dependency PRs (mirror host) |

The workflow expects these **secrets on the Forgejo repo or org**:

| Secret | Purpose |
| --- | --- |
| `RENOVATE_TOKEN` | Forgejo personal access token (or app token) with repo write for PR creation |
| `MIRROR_GITHUB_TOKEN` | Mapped to `GITHUB_COM_TOKEN` so Renovate can read release notes / changelogs on github.com |

## Human ops steps (Forgejo admin)

1. **Create a bot account or use a machine user** with access to `KyaniteLabs/kinocut`.
2. **Mint `RENOVATE_TOKEN`** with scopes that allow:
   - repository contents read
   - pull/PR create + write
   - issues write (labels/comments as needed by Renovate)
3. **Mint or reuse a GitHub PAT** (`MIRROR_GITHUB_TOKEN`) with `public_repo` (or fine-grained read on public deps) so github.com rate limits do not starve changelog lookups.
4. In Forgejo: **Settings → Actions → Secrets** (repo or org) set:
   - `RENOVATE_TOKEN`
   - `MIRROR_GITHUB_TOKEN`
5. Confirm the runner label used by `.forgejo/workflows/renovate.yml` (`heavy` today) is online.
6. Trigger once: Actions → **Renovate** → `workflow_dispatch`, or wait for the cron.
7. Verify a dependency PR opens (or logs show “no updates”).

## Optional hostRules (when github.com is blocked or needs a different token)

If the runner cannot reach github.com anonymously, extend `.renovaterc.json`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "automerge": true,
  "platformAutomerge": true,
  "hostRules": [
    {
      "hostType": "github",
      "matchHost": "github.com",
      "token": "{{ secrets.GITHUB_COM_TOKEN }}"
    }
  ]
}
```

Secrets must be injected via the workflow env (already sets `GITHUB_COM_TOKEN` from `MIRROR_GITHUB_TOKEN`). Do **not** commit real tokens.

## Done criteria for #3

- [ ] `RENOVATE_TOKEN` present on Forgejo host
- [ ] `MIRROR_GITHUB_TOKEN` present (for github.com)
- [ ] At least one successful Renovate workflow run (green or “no updates”)
- [ ] Optional: first dependency PR reviewed/merged

This file is the agent-closable runbook. Checking the boxes above is human/ops only.
