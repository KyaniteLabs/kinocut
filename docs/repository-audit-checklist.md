# Repository Audit Checklist (Step-by-Step)

Use this checklist to keep Kinocut at professional quality across code, docs, CI/CD, Forgejo/GitHub setup, and growth readiness.

## 1) Code health (weekly)

1. Run lint + formatting checks.
2. Run non-slow tests locally.
3. Validate package build and artifact surface.
4. Review recently touched modules for consistency with `CONTRIBUTING.md` conventions.

Suggested commands:

```bash
ruff check kinocut/ mcp_video.py
ruff format --check kinocut/ mcp_video.py
pytest tests/ -q -m "not slow" --tb=short
python -m build --sdist --wheel
python .github/scripts/check-built-artifacts.py dist
```

## 2) Git hygiene (before every PR)

1. Ensure branch has an upstream.
2. Ensure working tree is clean before review handoff.
3. Prune stale remotes.
4. Run the Git audit script.

```bash
git fetch --prune origin
./scripts/git-professional-audit.sh
```

## 3) Repository readiness (before releases)

Run:

```bash
./scripts/repo-readiness-audit.py
```

This validates:
- core community files exist
- issue/PR templates exist
- discussion templates exist
- CODEOWNERS and Dependabot config exist
- AI/search discovery files exist
- MCP Registry metadata exists
- workflow files exist
- README has key user onboarding sections
- package metadata URLs exist
- local tag visibility (release hygiene signal)

## 3.5) Integration smoke (before releases)

Run the dedicated smoke workflow after packaging or integration changes:

```bash
gh workflow run "Integration smoke"
```

This validates:
- base install imports and CLI help/version
- `kino doctor --json`
- a minimal FFmpeg trim path
- image extra import and tiny image color extraction
- Node/npm/npx availability reporting for Hyperframes
- AI module import and optional dependency reporting without installing heavyweight AI stacks

## 4) Documentation quality (weekly)

- README: accurate tool counts, install instructions, and quick-start snippets.
- Changelog/release notes: user-facing changes clearly summarized.
- Security/support docs: present and linked from README.
- Contributing docs: match real CI expectations.
- `llms.txt`: install commands, key files, safety rules, and canonical links stay current.
- `docs/AI_AGENT_DISCOVERY.md`: query targets and directory targets stay current.
- `server.json`: version and PyPI package metadata match `pyproject.toml`.

## 5) GitHub setup (monthly)

- Branch protection on `master` is enabled.
- Required status checks include CI.
- Signed tags are used for releases when possible.
- Discussions/Issues templates route users to the right channel.
- GitHub Pages deployment remains intentional and artifact-safe.
- Dependabot is grouped so dependency churn does not bury human work.
- CODEOWNERS routes review responsibility clearly.

## 6) Growth and accessibility (monthly)

- Keep issue templates concise and newcomer-friendly.
- Maintain a clear support path for questions.
- Ensure docs are scannable (headings, short paragraphs, command blocks).
- Prioritize fast “time to first success” in README.
- Keep `robots.txt`, `sitemap.xml`, and structured homepage metadata aligned with the GitHub Pages URL.
- Submit or update listings in MCP directories after meaningful releases.
- Publish/update the official MCP Registry entry after package releases.

## 7) Success metrics to track

- Time-to-first-success for new users.
- Issue response time.
- PR merge lead time.
- Release cadence consistency.
- Test pass rate stability.

Treat this as a living checklist: tighten checks whenever recurring problems appear.
