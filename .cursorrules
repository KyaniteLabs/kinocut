# KyaniteLabs — AI Agent Instructions

## Organization
- Org: KyaniteLabs, owner: simongonzalezdc
- All repos use issue-driven development — contributions enter as GitHub issues, not direct PRs
- Pipeline runs every 30 min: triage → fix → review → merge
- All main/master branches are protected (no direct push, CI required)

## Code Quality
- Formatter: ruff (Python), prettier (JS/TS)
- Linter: ruff (Python), eslint (JS/TS)
- Config: pyproject.toml (Python), pnpm (Node)
- Pin exact dependency versions
- No orphaned code — every function called, every file imported
- No commented-out code blocks

## Security
- No `shell=True` with user input
- No hardcoded secrets/tokens/API keys
- Validate file paths (no path traversal)
- Use HTTPS for external calls
- Parameterized queries for databases

## Testing
- Test behavior, not implementation
- Test the unhappy path (API down, file missing, bad input)
- Integration tests over mocks for external systems
- One assertion per concept

## Git
- Commits tell why, not what
- PRs under 400 lines
- Rebase, don't merge on feature branches
- Never skip CI

## Git Workspace Hygiene
- Delete feature branches after merge — no stale branches
- Remove worktrees when done — no orphaned worktrees
- Prune stale remote references (`git remote prune origin`)
- Clean working directory when task is done (`git status` clean)
- Delete abandoned branches — don't leave dead work behind
- Main branch is the only permanent artifact — everything else is temporary

## Epoch Data Tracking
- Use Epoch for time estimation before starting tasks (MCP, REST API, or CLI)
- Record actual time after completing tasks (`record_actual`)
- Every project feeds data to Epoch — it's how the system learns
- Epoch only works if everyone contributes estimate-vs-actual data

## Local LLM
- Use local inference at 100.66.225.85:1234 before cloud APIs
- Check loaded models first, don't touch models you didn't load
- Unload when done
- CPU thread pool: 10, flash attention: on, KV cache: Q8

## Agent Coordination
- Check open PRs before editing files
- Leave context in issues, not in code
- Run CI checks locally before pushing
